import ExpoModulesCore
import AVFoundation
import UIKit

public class ClarifyCoreModule: Module {
  private var computerScanning = false
  public func definition() -> ModuleDefinition {
    Name("ClarifyCore")
    Constant("uiLanguage") { ClarifyLocale.language }
    Function("newOperationID") { UUID().uuidString }
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
      return Onboarding().required(signedIn: ProcessingDestination.shared.configured)
    }.runOnQueue(.main)
    AsyncFunction("markOnboardingPresented") { Onboarding().presented() }.runOnQueue(.main)
    AsyncFunction("completeOnboarding") {
      try Onboarding().complete(configured: ProcessingDestination.shared.configured)
    }.runOnQueue(.main)
    AsyncFunction("getSnapshot") { () -> [String: Any] in
      let state = ClarifyAudioSession.shared.state
      let data = try JSONEncoder().encode(state)
      return try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
    }.runOnQueue(.main)
    AsyncFunction("getAccount") { () -> [String: Any] in ProcessingDestination.shared.snapshot() }.runOnQueue(.main)
    AsyncFunction("computerCommand") { (action: String, promise: Promise) in
      Task { @MainActor in
        do {
          let destination = ProcessingDestination.shared
          switch action {
          case "scan":
            guard !self.computerScanning, !CloudAccount.shared.isBusy, !ComputerConnection.shared.busy,
              let presenter = self.appContext?.utilities?.currentViewController() else { throw ComputerFailure.busy }
            self.computerScanning = true
            defer { self.computerScanning = false }
            // Clear ownership before opening a camera sheet or changing trust.
            ClarifyAudioSession.shared.destinationChanged()
            let context = destination.historyContext
            let qr = try await ComputerScanner.scan(from: presenter)
            guard context == destination.historyContext else { throw ComputerFailure.cancelled }
            try destination.select("computer")
            try await ComputerConnection.shared.pair(qr, deviceName: UIDevice.current.name)
            try? await ComputerConnection.shared.refresh()
          case "computer", "hosted":
            guard !self.computerScanning else { throw ComputerFailure.busy }
            try destination.select(action)
            ClarifyAudioSession.shared.destinationChanged()
          case "disconnect":
            ComputerConnection.shared.disconnect()
            ClarifyAudioSession.shared.destinationChanged()
          case "refresh": try await ComputerConnection.shared.refresh()
          default: throw ComputerFailure.invalidResponse
          }
          ClarifyAudioSession.shared.libraryChanged()
          promise.resolve(destination.snapshot())
        } catch {
          ClarifyAudioSession.shared.publish()
          promise.reject("COMPUTER_ERROR", (error as? ComputerFailure)?.localizedDescription ?? ComputerFailure.offline.localizedDescription)
        }
      }
    }.runOnQueue(.main)
    AsyncFunction("processComputerText") { (action: String, text: String, language: String, context: String, promise: Promise) in
      Task { @MainActor in
        do {
          guard context == ProcessingDestination.shared.historyContext,
            ProcessingDestination.shared.computerMode, !ClarifyAudioSession.shared.state.phase.busy else { throw ComputerFailure.busy }
          try await ProcessingDestination.shared.withComputerText(action, context: context) {
            guard !ClarifyAudioSession.shared.state.phase.busy else { throw ComputerFailure.busy }
            ClarifyAudioSession.shared.handleText(action, id: UUID().uuidString, text: text, language: language)
          }
          promise.resolve(nil)
        } catch { promise.reject("COMPUTER_ERROR", (error as? ComputerFailure)?.localizedDescription ?? ComputerFailure.offline.localizedDescription) }
      }
    }.runOnQueue(.main)
    AsyncFunction("accountCommand") { (action: String, value: String, promise: Promise) in
      Task { @MainActor in
        if self.computerScanning { promise.resolve(ProcessingDestination.shared.snapshot()); return }
        if ProcessingDestination.shared.computerMode {
          if action == "auto", !ComputerConnection.shared.busy, ComputerConnection.shared.configured,
             !ClarifyAudioSession.shared.state.phase.busy {
            _ = try? await ProcessingDestination.shared.automaticRefresh(ClarifyAudioSession.shared.library())
          }
          promise.resolve(ProcessingDestination.shared.snapshot()); return
        }
        guard !ClarifyAudioSession.shared.state.phase.busy else {
          if action == "auto" { promise.resolve(ProcessingDestination.shared.snapshot()); return }
          promise.reject("ACCOUNT_BUSY", L("Finalize o ditado antes de alterar a conta.")); return
        }
        do {
          let previousScope = CloudAccount.shared.scope
          let previousContext = ProcessingDestination.shared.historyContext
          // Pending keyboard edits stay durable if import fails. They must not
          // prevent signing out, deleting the account or freeing dictionary space.
          try? ClarifyAudioSession.shared.importKeyboardVocabulary()
          let changed: Bool
          if action == "auto" { changed = try await ProcessingDestination.shared.automaticRefresh(ClarifyAudioSession.shared.library()) }
          else { changed = try await CloudAccount.shared.command(action, value: value, library: ClarifyAudioSession.shared.library()) }
          if action == "delete", let previousScope { try SharedState()?.discardKeyboardAdditions(scope: previousScope) }
          if previousContext != ProcessingDestination.shared.historyContext { ClarifyAudioSession.shared.destinationChanged() }
          if changed {
            if !CloudAccount.shared.configured { ClarifyAudioSession.shared.deactivate() }
            ClarifyAudioSession.shared.libraryChanged()
          }
          ClarifyAudioSession.shared.syncHistory(force: action == "confirm" || action == "social")
          promise.resolve(ProcessingDestination.shared.snapshot())
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
      Task { @MainActor in
        do {
          try await ProcessingDestination.shared.withActivation(prepare: {
            let allowed = await withCheckedContinuation { continuation in
              AVAudioSession.sharedInstance().requestRecordPermission { continuation.resume(returning: $0) }
            }
            guard allowed else { throw ClarifyError(L("Ative o microfone em Ajustes > Clarify.")) }
            // The permission sheet and keyboard handoff can leave the app inactive.
            // Start audio only after that transition, and never from the background.
            let deadline = Date().addingTimeInterval(2)
            while UIApplication.shared.applicationState == .inactive, Date() < deadline {
              try await Task.sleep(nanoseconds: 50_000_000)
            }
          }, activate: {
            // Account refresh can suspend after the permission sheet closes.
            guard UIApplication.shared.applicationState == .active else {
              throw ClarifyError(L("Mantenha o Clarify aberto e tente ativar o microfone novamente."))
            }
            try ClarifyAudioSession.shared.activate()
          })
          promise.resolve(["active": true])
        } catch { promise.resolve(["active": false, "message": (error as? ComputerFailure)?.localizedDescription ?? MicrophoneFailure.message(for: error)] as [String: Any]) }
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
    AsyncFunction("command") { (action: String, operationID: String, context: String) in
      guard context == ProcessingDestination.shared.historyContext else { return }
      ClarifyAudioSession.shared.handle(action, id: operationID)
    }.runOnQueue(.main)
    AsyncFunction("copyResult") {
      if let text = ClarifyAudioSession.shared.state.text { UIPasteboard.general.string = text }
    }.runOnQueue(.main)
    AsyncFunction("copyText") { (text: String) in UIPasteboard.general.string = text }.runOnQueue(.main)
    AsyncFunction("getHistory") { (before: String) -> [String: Any] in
      let page = try ClarifyAudioSession.shared.library().history(before: before, scope: ProcessingDestination.shared.historyScope, includeLocal: !ProcessingDestination.shared.computerMode)
      var result = try JSONSerialization.jsonObject(with: JSONEncoder().encode(page)) as? [String: Any] ?? [:]
      result["context"] = ProcessingDestination.shared.historyContext
      if var entries = result["entries"] as? [[String: Any]] {
        for index in entries.indices {
          entries[index]["localOnly"] = page.localEntries[index]
          entries[index]["context"] = ProcessingDestination.shared.historyContext
        }
        result["entries"] = entries
      }
      result.removeValue(forKey: "localEntries")
      return result
    }.runOnQueue(.main)
    AsyncFunction("deleteHistory") { (id: String, localOnly: Bool, context: String) in
      guard context == ProcessingDestination.shared.historyContext else { throw ClarifyError(L("A conta mudou. Abra o histórico novamente.")) }
      try ClarifyAudioSession.shared.library().deleteHistory(id, scope: (localOnly && !ProcessingDestination.shared.computerMode) ? nil : ProcessingDestination.shared.historyScope)
      ClarifyAudioSession.shared.libraryChanged()
      ClarifyAudioSession.shared.syncHistory(force: true)
    }.runOnQueue(.main)
    AsyncFunction("clearHistory") { (context: String) in
      guard context == ProcessingDestination.shared.historyContext else { throw ClarifyError(L("A conta mudou. Abra o histórico novamente.")) }
      guard !ClarifyAudioSession.shared.state.phase.busy else { throw ClarifyError(L("Finalize a gravação antes de apagar o histórico.")) }
      try ClarifyAudioSession.shared.library().clearHistory(scope: ProcessingDestination.shared.historyScope, includeLocal: !ProcessingDestination.shared.computerMode)
      ClarifyAudioSession.shared.libraryChanged()
      ClarifyAudioSession.shared.syncHistory(force: true)
    }.runOnQueue(.main)
    AsyncFunction("getDictionary") { () -> [[String: Any]] in
      if ProcessingDestination.shared.computerMode { return [] }
      try? ClarifyAudioSession.shared.importKeyboardVocabulary()
      try CloudAccount.shared.prepareLibrary(ClarifyAudioSession.shared.library())
      let entries = try ClarifyAudioSession.shared.library().dictionary(scope: CloudAccount.shared.scope)
      return try JSONSerialization.jsonObject(with: JSONEncoder().encode(entries)) as? [[String: Any]] ?? []
    }.runOnQueue(.main)
    AsyncFunction("saveDictionary") { (values: [[String: Any]], base: [[String: Any]], promise: Promise) in
      Task { @MainActor in
        guard !ProcessingDestination.shared.computerMode else { promise.reject("COMPUTER_LIBRARY", L("Use o dicionário e os snippets configurados no computador.")); return }
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
      if ProcessingDestination.shared.computerMode { return [] }
      guard !CloudAccount.shared.managed || CloudAccount.shared.snippetScope != nil else { throw ClarifyError(L("Entre na conta novamente.")) }
      let entries = try ClarifyAudioSession.shared.library().snippets(scope: CloudAccount.shared.snippetScope)
      return try JSONSerialization.jsonObject(with: JSONEncoder().encode(entries)) as? [[String: Any]] ?? []
    }.runOnQueue(.main)
    AsyncFunction("saveSnippets") { (values: [[String: Any]], base: [[String: Any]], context: String, promise: Promise) in
      Task { @MainActor in
        guard !ProcessingDestination.shared.computerMode else { promise.reject("COMPUTER_LIBRARY", L("Use o dicionário e os snippets configurados no computador.")); return }
        guard !ClarifyAudioSession.shared.state.phase.busy, !CloudAccount.shared.isBusy else { promise.reject("ACCOUNT_BUSY", L("Aguarde a operação da conta.")); return }
        do {
          let entries = try JSONDecoder().decode([Snippet].self, from: JSONSerialization.data(withJSONObject: values))
          let original = try JSONDecoder().decode([Snippet].self, from: JSONSerialization.data(withJSONObject: base))
          let library = try ClarifyAudioSession.shared.library()
          guard context == ProcessingDestination.shared.historyContext else { throw CancellationError() }
          try CloudAccount.shared.saveSnippetDraft(entries, base: original, context: CloudAccount.shared.historyContext, library: library)
          if CloudAccount.shared.scope != nil { await CloudAccount.shared.syncAfterSave(library) }
          ClarifyAudioSession.shared.libraryChanged()
          promise.resolve(nil)
        } catch { promise.reject("SNIPPET_ERROR", error.localizedDescription) }
      }
    }.runOnQueue(.main)
  }
}
