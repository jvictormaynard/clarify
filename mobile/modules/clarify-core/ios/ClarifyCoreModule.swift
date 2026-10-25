import ExpoModulesCore
import AVFoundation
import UIKit

public class ClarifyCoreModule: Module {
  public func definition() -> ModuleDefinition {
    Name("ClarifyCore")
    Constant("uiLanguage") { ClarifyLocale.language }
    Constant("keyboardDiagnosticAvailable") { Bundle.main.object(forInfoDictionaryKey: "ClarifyKeyboardDiagnostic") as? Bool == true }
    AsyncFunction("openKeyboardDiagnostic") { (promise: Promise) in
      Task { @MainActor in
        guard Bundle.main.object(forInfoDictionaryKey: "ClarifyKeyboardDiagnostic") as? Bool == true,
              UIApplication.shared.applicationState == .active,
              !ClarifyAudioSession.shared.state.phase.busy,
              let presenter = self.appContext?.utilities?.currentViewController(),
              presenter.presentedViewController == nil else {
          promise.reject("KEYBOARD_TEST", L("Não foi possível abrir o teste do teclado. Tente novamente.")); return
        }
        let navigation = UINavigationController(rootViewController: KeyboardOpeningDiagnostic())
        navigation.modalPresentationStyle = .fullScreen
        presenter.present(navigation, animated: true) { promise.resolve(nil) }
      }
    }.runOnQueue(.main)
    AsyncFunction("onboardingRequired") { () -> Bool in
      return Onboarding().required(signedIn: CloudAccount.shared.configured)
    }.runOnQueue(.main)
    AsyncFunction("completeOnboarding") {
      try Onboarding().complete(configured: CloudAccount.shared.configured)
    }.runOnQueue(.main)
    AsyncFunction("getSnapshot") { () -> [String: Any] in
      let state = ClarifyAudioSession.shared.state
      let data = try JSONEncoder().encode(state)
      return try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
    }.runOnQueue(.main)
    AsyncFunction("getAccount") { () -> [String: Any] in CloudAccount.shared.snapshot() }.runOnQueue(.main)
    AsyncFunction("accountCommand") { (action: String, value: String, promise: Promise) in
      Task { @MainActor in
        guard !ClarifyAudioSession.shared.state.phase.busy else {
          if action == "auto" { promise.resolve(CloudAccount.shared.snapshot()); return }
          promise.reject("ACCOUNT_BUSY", L("Finalize o ditado antes de alterar a conta.")); return
        }
        do {
          let previousScope = CloudAccount.shared.scope
          // Pending keyboard edits stay durable if import fails. They must not
          // prevent signing out, deleting the account or freeing dictionary space.
          try? ClarifyAudioSession.shared.importKeyboardVocabulary()
          let changed = try await CloudAccount.shared.command(action, value: value, library: ClarifyAudioSession.shared.library())
          if action == "delete", let previousScope { try SharedState()?.discardKeyboardAdditions(scope: previousScope) }
          if changed {
            if !CloudAccount.shared.configured { ClarifyAudioSession.shared.deactivate() }
            ClarifyAudioSession.shared.libraryChanged()
          }
          ClarifyAudioSession.shared.syncHistory(force: action == "confirm" || action == "social")
          promise.resolve(CloudAccount.shared.snapshot())
        } catch {
          if !CloudAccount.shared.configured, ClarifyAudioSession.shared.state.sessionActive {
            ClarifyAudioSession.shared.accountSessionInvalidated()
          }
          ClarifyAudioSession.shared.libraryChanged()
          promise.reject("ACCOUNT_ERROR", error is ClarifyError ? error.localizedDescription : L("Não foi possível acessar o Clarify. Verifique a conexão."))
        }
      }
    }.runOnQueue(.main)
    AsyncFunction("activate") { (promise: Promise) in
      guard !CloudAccount.shared.isBusy else {
        promise.resolve(["active": false, "message": L("Aguarde a operação da conta.")] as [String: Any]); return
      }
      AVAudioSession.sharedInstance().requestRecordPermission { allowed in
        Task { @MainActor in
          guard allowed else { promise.resolve(["active": false, "message": L("Ative o microfone em Ajustes > Clarify.")] as [String: Any]); return }
          // The permission sheet and keyboard handoff can leave the app inactive.
          // Start audio only after that transition, and never from the background.
          let deadline = Date().addingTimeInterval(2)
          while UIApplication.shared.applicationState == .inactive, Date() < deadline {
            try? await Task.sleep(nanoseconds: 50_000_000)
          }
          guard UIApplication.shared.applicationState == .active else {
            promise.resolve(["active": false, "message": L("Mantenha o Clarify aberto e tente ativar o microfone novamente.")] as [String: Any]); return
          }
          do { try ClarifyAudioSession.shared.activate(); promise.resolve(["active": true]) }
          catch { promise.resolve(["active": false, "message": MicrophoneFailure.message(for: error)] as [String: Any]) }
        }
      }
    }.runOnQueue(.main)
    AsyncFunction("deactivate") { ClarifyAudioSession.shared.deactivate() }.runOnQueue(.main)
    AsyncFunction("returnToSource") { (token: String, promise: Promise) in
      Task { @MainActor in
        // Permission alerts temporarily make the app inactive. Wait for that
        // transition, but never launch another app while Clarify is backgrounded.
        let deadline = Date().addingTimeInterval(2)
        while UIApplication.shared.applicationState == .inactive, Date() < deadline {
          try? await Task.sleep(nanoseconds: 50_000_000)
        }
        guard UIApplication.shared.applicationState == .active,
              ClarifyAudioSession.shared.state.sessionActive, !ClarifyAudioSession.shared.state.phase.busy,
              let request = SharedState()?.consumeActivation(token) else { promise.resolve(false); return }
        promise.resolve(ClarifyReturnBridge.openSource(bundleID: request.sourceBundleID))
      }
    }.runOnQueue(.main)
    AsyncFunction("command") { (action: String, operationID: String) in
      ClarifyAudioSession.shared.handle(action, id: operationID)
    }.runOnQueue(.main)
    AsyncFunction("copyResult") {
      if let text = ClarifyAudioSession.shared.state.text { UIPasteboard.general.string = text }
    }.runOnQueue(.main)
    AsyncFunction("copyText") { (text: String) in UIPasteboard.general.string = text }.runOnQueue(.main)
    AsyncFunction("getHistory") { (before: String) -> [String: Any] in
      let page = try ClarifyAudioSession.shared.library().history(before: before, scope: CloudAccount.shared.historyScope)
      var result = try JSONSerialization.jsonObject(with: JSONEncoder().encode(page)) as? [String: Any] ?? [:]
      result["context"] = CloudAccount.shared.historyContext
      if var entries = result["entries"] as? [[String: Any]] {
        for index in entries.indices {
          entries[index]["localOnly"] = page.localEntries[index]
          entries[index]["context"] = CloudAccount.shared.historyContext
        }
        result["entries"] = entries
      }
      result.removeValue(forKey: "localEntries")
      return result
    }.runOnQueue(.main)
    AsyncFunction("deleteHistory") { (id: String, localOnly: Bool, context: String) in
      guard context == CloudAccount.shared.historyContext else { throw ClarifyError(L("A conta mudou. Abra o histórico novamente.")) }
      try ClarifyAudioSession.shared.library().deleteHistory(id, scope: localOnly ? nil : CloudAccount.shared.historyScope)
      ClarifyAudioSession.shared.libraryChanged()
      ClarifyAudioSession.shared.syncHistory(force: true)
    }.runOnQueue(.main)
    AsyncFunction("clearHistory") { (context: String) in
      guard context == CloudAccount.shared.historyContext else { throw ClarifyError(L("A conta mudou. Abra o histórico novamente.")) }
      guard !ClarifyAudioSession.shared.state.phase.busy else { throw ClarifyError(L("Finalize a gravação antes de apagar o histórico.")) }
      try ClarifyAudioSession.shared.library().clearHistory(scope: CloudAccount.shared.historyScope)
      ClarifyAudioSession.shared.libraryChanged()
      ClarifyAudioSession.shared.syncHistory(force: true)
    }.runOnQueue(.main)
    AsyncFunction("getDictionary") { () -> [[String: Any]] in
      try? ClarifyAudioSession.shared.importKeyboardVocabulary()
      try CloudAccount.shared.prepareLibrary(ClarifyAudioSession.shared.library())
      let entries = try ClarifyAudioSession.shared.library().dictionary(scope: CloudAccount.shared.scope)
      return try JSONSerialization.jsonObject(with: JSONEncoder().encode(entries)) as? [[String: Any]] ?? []
    }.runOnQueue(.main)
    AsyncFunction("saveDictionary") { (values: [[String: Any]], base: [[String: Any]], promise: Promise) in
      Task { @MainActor in
        guard !ClarifyAudioSession.shared.state.phase.busy, !CloudAccount.shared.isBusy else { promise.reject("ACCOUNT_BUSY", L("Finalize a operação antes de alterar o dicionário.")); return }
        do {
          let entries = try JSONDecoder().decode([VocabularyEntry].self, from: JSONSerialization.data(withJSONObject: values))
          let original = try JSONDecoder().decode([VocabularyEntry].self, from: JSONSerialization.data(withJSONObject: base))
          let library = try ClarifyAudioSession.shared.library()
          try? ClarifyAudioSession.shared.importKeyboardVocabulary()
          try CloudAccount.shared.saveDictionaryDraft(entries, base: original, library: library)
          if CloudAccount.shared.scope != nil { await CloudAccount.shared.syncAfterSave(library) }
          ClarifyAudioSession.shared.libraryChanged()
          promise.resolve(nil)
        } catch { promise.reject("DICTIONARY_ERROR", error.localizedDescription) }
      }
    }.runOnQueue(.main)
    AsyncFunction("getSnippets") { () -> [[String: Any]] in
      guard !CloudAccount.shared.managed || CloudAccount.shared.snippetScope != nil else { throw ClarifyError(L("Entre na conta novamente.")) }
      let entries = try ClarifyAudioSession.shared.library().snippets(scope: CloudAccount.shared.snippetScope)
      return try JSONSerialization.jsonObject(with: JSONEncoder().encode(entries)) as? [[String: Any]] ?? []
    }.runOnQueue(.main)
    AsyncFunction("saveSnippets") { (values: [[String: Any]], base: [[String: Any]], context: String, promise: Promise) in
      Task { @MainActor in
        guard !ClarifyAudioSession.shared.state.phase.busy, !CloudAccount.shared.isBusy else { promise.reject("ACCOUNT_BUSY", L("Aguarde a operação da conta.")); return }
        do {
          let entries = try JSONDecoder().decode([Snippet].self, from: JSONSerialization.data(withJSONObject: values))
          let original = try JSONDecoder().decode([Snippet].self, from: JSONSerialization.data(withJSONObject: base))
          let library = try ClarifyAudioSession.shared.library()
          try CloudAccount.shared.saveSnippetDraft(entries, base: original, context: context, library: library)
          if CloudAccount.shared.scope != nil { await CloudAccount.shared.syncAfterSave(library) }
          ClarifyAudioSession.shared.libraryChanged()
          promise.resolve(nil)
        } catch { promise.reject("SNIPPET_ERROR", error.localizedDescription) }
      }
    }.runOnQueue(.main)
  }
}
