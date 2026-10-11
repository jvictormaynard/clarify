import ExpoModulesCore
import AVFoundation
import UIKit

public class ClarifyCoreModule: Module {
  public func definition() -> ModuleDefinition {
    Name("ClarifyCore")
    Constant("uiLanguage") { ClarifyLocale.language }
    AsyncFunction("onboardingRequired") { () -> Bool in
      let account = CloudAccount.shared.snapshot()
      return Onboarding().required(existingSetup: account["signedIn"] as? Bool == true || KeyStore.read() != nil)
    }.runOnQueue(.main)
    AsyncFunction("completeOnboarding") { (mode: String) in
      let account = CloudAccount.shared.snapshot()
      let ready = mode == "account" ? CloudAccount.shared.hosted && CloudAccount.shared.configured
        : mode == "byok" && KeyStore.read() != nil && (account["signedIn"] as? Bool != true)
      try Onboarding().complete(configured: ready)
    }.runOnQueue(.main)
    AsyncFunction("getSnapshot") { () -> [String: Any] in
      let state = ClarifyAudioSession.shared.state
      let data = try JSONEncoder().encode(state)
      return try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
    }.runOnQueue(.main)
    AsyncFunction("setKey") { (key: String) in try ClarifyAudioSession.shared.saveKey(key) }.runOnQueue(.main)
    AsyncFunction("getAccount") { () -> [String: Any] in CloudAccount.shared.snapshot() }.runOnQueue(.main)
    AsyncFunction("accountCommand") { (action: String, value: String, promise: Promise) in
      Task { @MainActor in
        guard !ClarifyAudioSession.shared.state.phase.busy else {
          if action == "auto" { promise.resolve(CloudAccount.shared.snapshot()); return }
          promise.reject("ACCOUNT_BUSY", L("Finalize o ditado antes de alterar a conta.")); return
        }
        do {
          let changed = try await CloudAccount.shared.command(action, value: value, library: ClarifyAudioSession.shared.library())
          if changed {
            if !CloudAccount.shared.configured { ClarifyAudioSession.shared.deactivate() }
            ClarifyAudioSession.shared.libraryChanged()
          }
          promise.resolve(CloudAccount.shared.snapshot())
        } catch {
          ClarifyAudioSession.shared.libraryChanged()
          promise.reject("ACCOUNT_ERROR", error is ClarifyError ? error.localizedDescription : L("Não foi possível acessar o Clarify. Verifique a conexão."))
        }
      }
    }.runOnQueue(.main)
    AsyncFunction("activate") { (promise: Promise) in
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
    AsyncFunction("getHistory") { (before: Int64) -> [String: Any] in
      let page = try ClarifyAudioSession.shared.library().history(before: max(0, before))
      return try JSONSerialization.jsonObject(with: JSONEncoder().encode(page)) as? [String: Any] ?? [:]
    }.runOnQueue(.main)
    AsyncFunction("deleteHistory") { (id: String) in
      try ClarifyAudioSession.shared.library().deleteHistory(id)
      ClarifyAudioSession.shared.libraryChanged()
    }.runOnQueue(.main)
    AsyncFunction("clearHistory") {
      guard !ClarifyAudioSession.shared.state.phase.busy else { throw ClarifyError(L("Finalize a gravação antes de apagar o histórico.")) }
      try ClarifyAudioSession.shared.library().clearHistory()
      ClarifyAudioSession.shared.libraryChanged()
    }.runOnQueue(.main)
    AsyncFunction("getDictionary") { () -> [[String: Any]] in
      try CloudAccount.shared.prepareLibrary(ClarifyAudioSession.shared.library())
      let entries = try ClarifyAudioSession.shared.library().dictionary(scope: CloudAccount.shared.scope)
      return try JSONSerialization.jsonObject(with: JSONEncoder().encode(entries)) as? [[String: Any]] ?? []
    }.runOnQueue(.main)
    AsyncFunction("saveDictionary") { (values: [[String: Any]], promise: Promise) in
      Task { @MainActor in
        guard !ClarifyAudioSession.shared.state.phase.busy, !CloudAccount.shared.isBusy else { promise.reject("ACCOUNT_BUSY", L("Finalize a operação antes de alterar o dicionário.")); return }
        do {
          let entries = try JSONDecoder().decode([VocabularyEntry].self, from: JSONSerialization.data(withJSONObject: values))
          let library = try ClarifyAudioSession.shared.library()
          try library.saveDictionary(entries, scope: CloudAccount.shared.scope)
          if CloudAccount.shared.scope != nil { await CloudAccount.shared.syncAfterSave(library) }
          ClarifyAudioSession.shared.libraryChanged()
          promise.resolve(nil)
        } catch { promise.reject("DICTIONARY_ERROR", error.localizedDescription) }
      }
    }.runOnQueue(.main)
  }
}
