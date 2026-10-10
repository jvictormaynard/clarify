import ExpoModulesCore
import AVFoundation
import UIKit

public class ClarifyCoreModule: Module {
  public func definition() -> ModuleDefinition {
    Name("ClarifyCore")
    AsyncFunction("getSnapshot") { () -> [String: Any] in
      let state = ClarifyAudioSession.shared.state
      let data = try JSONEncoder().encode(state)
      return try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
    }.runOnQueue(.main)
    AsyncFunction("setKey") { (key: String) in try ClarifyAudioSession.shared.saveKey(key) }.runOnQueue(.main)
    AsyncFunction("activate") { (promise: Promise) in
      AVAudioSession.sharedInstance().requestRecordPermission { allowed in
        Task { @MainActor in
          guard allowed else { promise.resolve(["active": false, "message": "Ative o microfone em Ajustes > Clarify."] as [String: Any]); return }
          // The permission sheet and keyboard handoff can leave the app inactive.
          // Start audio only after that transition, and never from the background.
          let deadline = Date().addingTimeInterval(2)
          while UIApplication.shared.applicationState == .inactive, Date() < deadline {
            try? await Task.sleep(nanoseconds: 50_000_000)
          }
          guard UIApplication.shared.applicationState == .active else {
            promise.resolve(["active": false, "message": "Mantenha o Clarify aberto e tente ativar o microfone novamente."] as [String: Any]); return
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
      guard !ClarifyAudioSession.shared.state.phase.busy else { throw ClarifyError("Finalize a gravação antes de apagar o histórico.") }
      try ClarifyAudioSession.shared.library().clearHistory()
      ClarifyAudioSession.shared.libraryChanged()
    }.runOnQueue(.main)
    AsyncFunction("getDictionary") { () -> [[String: Any]] in
      let entries = try ClarifyAudioSession.shared.library().dictionary()
      return try JSONSerialization.jsonObject(with: JSONEncoder().encode(entries)) as? [[String: Any]] ?? []
    }.runOnQueue(.main)
    AsyncFunction("saveDictionary") { (values: [[String: Any]]) in
      guard !ClarifyAudioSession.shared.state.phase.busy else { throw ClarifyError("Finalize a gravação antes de alterar o dicionário.") }
      let entries = try JSONDecoder().decode([VocabularyEntry].self, from: JSONSerialization.data(withJSONObject: values))
      try ClarifyAudioSession.shared.library().saveDictionary(entries)
      ClarifyAudioSession.shared.libraryChanged()
    }.runOnQueue(.main)
  }
}
