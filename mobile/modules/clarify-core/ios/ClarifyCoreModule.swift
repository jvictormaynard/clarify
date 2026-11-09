import ExpoModulesCore
import AVFoundation
import UIKit

public class ClarifyCoreModule: Module {
  private var computerScanning = false
  private var appleRewriteTask: Task<Void, Never>?
  private var appleRewriteID: String?
  private var appleLabLastRejection = "none"
  private var appleLabLastAdmission: [String: Any] = [:]
  @MainActor private func appleLabAdmission() -> AppleLabAdmission {
    AppleLabAdmission(active: UIApplication.shared.applicationState == .active,
      labBusy: appleRewriteTask != nil,
      privateBusy: ClarifyPrivateWritingToolsBridge.isBusy(), scanning: computerScanning,
      phase: ClarifyAudioSession.shared.state.phase,
      remoteBusy: ProcessingDestination.shared.isBusy)
  }
  @MainActor private func rejectAppleLab(_ promise: Promise, reason: String) {
    appleLabLastRejection = reason
    appleLabLastAdmission = appleLabAdmission().snapshot
    appleLabLastAdmission["blockedBy"] = reason
    let message: String
    switch reason {
    case "app_inactive": message = "Keep Clarify in the foreground to run this test."
    case "apple_test_busy": message = "An Apple test is running. Cancel it or wait for it to finish."
    case "private_session_busy": message = "Close the private Writing Tools editor before starting another test."
    case "scanner_open": message = "Close the QR scanner before starting an Apple test."
    case "dictation_busy": message = "Finish or cancel dictation before starting an Apple test."
    case "presentation_busy": message = "Close the current sheet before opening Writing Tools."
    default: message = "The Apple test could not start. Inspect the interface report."
    }
    promise.reject("APPLE_REWRITE", L(message) + " [" + reason + "]")
  }
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
    AsyncFunction("getKeyboardAutocorrectEnabled") { () -> Bool in
      SharedState()?.keyboardAutocorrectEnabled() ?? false
    }.runOnQueue(.main)
    AsyncFunction("setKeyboardAutocorrectEnabled") { (enabled: Bool) in
      guard let store = SharedState() else { throw ClarifyError(L("Não foi possível acessar os dados do teclado.")) }
      try store.setKeyboardAutocorrectEnabled(enabled)
    }.runOnQueue(.main)
    AsyncFunction("getOutputPreferences") { () -> [String: String] in
      (SharedState()?.outputPreferences() ?? OutputPreferences()).snapshot
    }.runOnQueue(.main)
    AsyncFunction("getAppleRewriteAvailability") { () -> [String: Any] in
      AppleRewriteEngine.availability()
    }.runOnQueue(.main)
    AsyncFunction("rewriteWithApple") { (id: String, source: String, language: String, style: String, promise: Promise) in
      Task { @MainActor in
        guard UUID(uuidString: id) != nil, let language = OutputLanguage(rawValue: language),
          let style = OutputStyle(rawValue: style) else {
          promise.reject("APPLE_REWRITE", L("The rewrite request is invalid.")); return
        }
        if let reason = self.appleLabAdmission().blockReason {
          self.rejectAppleLab(promise, reason: reason); return
        }
        self.appleRewriteID = id
        let preferences = OutputPreferences(language: language, style: style)
        self.appleRewriteTask = Task { @MainActor in
          defer {
            if self.appleRewriteID == id { self.appleRewriteID = nil; self.appleRewriteTask = nil }
          }
          do {
            let result = try await AppleRewriteEngine.rewrite(source, preferences: preferences)
            try Task.checkCancellation()
            guard self.appleRewriteID == id, UIApplication.shared.applicationState == .active else { throw CancellationError() }
            promise.resolve(result)
          } catch is CancellationError {
            promise.reject("APPLE_REWRITE", L("Cancelled"))
          } catch {
            promise.reject("APPLE_REWRITE", error.localizedDescription)
          }
        }
      }
    }.runOnQueue(.main)
    AsyncFunction("rewriteWithAppleReport") { (id: String, source: String, language: String, style: String, deterministic: Bool, promise: Promise) in
      Task { @MainActor in
        guard UUID(uuidString: id) != nil, let language = OutputLanguage(rawValue: language),
          let style = OutputStyle(rawValue: style) else {
          promise.reject("APPLE_REWRITE", L("The rewrite request is invalid.")); return
        }
        if let reason = self.appleLabAdmission().blockReason {
          self.rejectAppleLab(promise, reason: reason); return
        }
        self.appleRewriteID = id
        let preferences = OutputPreferences(language: language, style: style)
        self.appleRewriteTask = Task { @MainActor in
          defer {
            if self.appleRewriteID == id { self.appleRewriteID = nil; self.appleRewriteTask = nil }
          }
          do {
            let result = try await AppleRewriteEngine.rewriteReport(source, preferences: preferences, deterministic: deterministic)
            try Task.checkCancellation()
            guard self.appleRewriteID == id, UIApplication.shared.applicationState == .active else { throw CancellationError() }
            promise.resolve(result.snapshot)
          } catch is CancellationError {
            promise.reject("APPLE_REWRITE", L("Cancelled"))
          } catch {
            promise.reject("APPLE_REWRITE", error.localizedDescription)
          }
        }
      }
    }.runOnQueue(.main)
    AsyncFunction("rewriteWithPrivateAppleReport") { (id: String, source: String, language: String, style: String, promise: Promise) in
      Task { @MainActor in
        guard UUID(uuidString: id) != nil, let language = OutputLanguage(rawValue: language),
          let style = OutputStyle(rawValue: style) else {
          promise.reject("APPLE_REWRITE", L("The rewrite request is invalid.")); return
        }
        if let reason = self.appleLabAdmission().blockReason {
          self.rejectAppleLab(promise, reason: reason); return
        }
        self.appleRewriteID = id
        let preferences = OutputPreferences(language: language, style: style)
        self.appleRewriteTask = Task { @MainActor in
          defer {
            if self.appleRewriteID == id { self.appleRewriteID = nil; self.appleRewriteTask = nil }
          }
          do {
            let result = try await ApplePrivateRewrite.report(source, preferences: preferences, operationID: id)
            try Task.checkCancellation()
            guard self.appleRewriteID == id, UIApplication.shared.applicationState == .active else { throw CancellationError() }
            promise.resolve(result.snapshot)
          } catch is CancellationError {
            promise.reject("APPLE_REWRITE", L("Cancelled"))
          } catch {
            promise.reject("APPLE_REWRITE", error.localizedDescription)
          }
        }
      }
    }.runOnQueue(.main)
    AsyncFunction("getPrivateAppleRewriteProbe") { (promise: Promise) in
      Task { @MainActor in
        var report = ClarifyPrivateWritingToolsBridge.probe()
        report["admission"] = self.appleLabAdmission().snapshot
        report["lastRejectedBy"] = self.appleLabLastRejection
        report["lastRejectedAdmission"] = self.appleLabLastAdmission
        report["mainThread"] = Thread.isMainThread
        promise.resolve(report)
      }
    }.runOnQueue(.main)
    AsyncFunction("openAppleWritingTools") { (source: String, language: String, promise: Promise) in
      Task { @MainActor in
        guard !source.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
          source.utf8.count <= AppleRewriteEngine.maxInputBytes,
          OutputLanguage(rawValue: language) != nil else {
          promise.reject("APPLE_REWRITE", L("The rewrite request is invalid.")); return
        }
        if let reason = self.appleLabAdmission().blockReason {
          self.rejectAppleLab(promise, reason: reason); return
        }
        guard let presenter = self.appContext?.utilities?.currentViewController(),
          presenter.presentedViewController == nil else {
          self.rejectAppleLab(promise, reason: "presentation_busy"); return
        }
        let editor = AppleWritingToolsController(source: source, target: language)
        presenter.present(UINavigationController(rootViewController: editor), animated: true) { promise.resolve(nil) }
      }
    }.runOnQueue(.main)
    AsyncFunction("openPrivateAppleWritingTools") { (source: String, language: String, style: String, promise: Promise) in
      Task { @MainActor in
        guard !source.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
          source.utf8.count <= AppleRewriteEngine.maxInputBytes,
          OutputLanguage(rawValue: language) != nil,
          OutputStyle(rawValue: style) != nil else {
          promise.reject("APPLE_REWRITE", L("The rewrite request is invalid.")); return
        }
        if let reason = self.appleLabAdmission().blockReason {
          self.rejectAppleLab(promise, reason: reason); return
        }
        guard let presenter = self.appContext?.utilities?.currentViewController(),
          presenter.presentedViewController == nil else {
          self.rejectAppleLab(promise, reason: "presentation_busy"); return
        }
        let editor = AppleWritingToolsController(source: source, target: language, privateStyle: style)
        presenter.present(UINavigationController(rootViewController: editor), animated: true) { promise.resolve(nil) }
      }
    }.runOnQueue(.main)
    AsyncFunction("cancelAppleRewrite") { (id: String, promise: Promise) in
      Task { @MainActor in
        guard self.appleRewriteID == id, let task = self.appleRewriteTask else { promise.resolve(nil); return }
        task.cancel()
        ClarifyPrivateWritingToolsBridge.cancelOperation(id)
        await task.value
        promise.resolve(nil)
      }
    }.runOnQueue(.main)
    AsyncFunction("setOutputPreference") { (key: String, value: String) -> [String: String] in
      guard let store = SharedState() else { throw ClarifyError(L("Não foi possível acessar os dados do teclado.")) }
      return try store.setOutputPreference(key, value: value).snapshot
    }.runOnQueue(.main)
    AsyncFunction("getDictationPolicy") { () -> [String: String] in
      DictationPolicyStore().read(scope: ProcessingDestination.shared.historyScope ?? "").snapshot
    }.runOnQueue(.main)
    AsyncFunction("setDictationPolicy") { (mode: String, actionID: String, revision: String, language: String, context: String) -> [String: String] in
      let destination = ProcessingDestination.shared
      guard destination.configured, context == destination.historyContext, let scope = destination.historyScope,
        let selected = DictationMode(rawValue: mode),
        let target = OutputLanguage(rawValue: language) else { throw ComputerFailure.notReady }
      let policy = DictationPolicy(mode: selected, actionID: selected == .action ? actionID : "",
        actionRevision: selected == .action ? revision : "", language: target)
      _ = try destination.dictationFields(policy)
      try DictationPolicyStore().save(policy, scope: scope)
      return policy.snapshot
    }.runOnQueue(.main)
    AsyncFunction("processText") { (action: String, text: String, language: String, context: String, promise: Promise) in
      Task { @MainActor in
        do {
          guard ["rewrite", "translate"].contains(action) else { throw ComputerFailure.invalidResponse }
          promise.resolve(try await ClarifyAudioSession.shared.startText(action, text: text, language: language, context: context))
        } catch { promise.reject("TEXT_ERROR", error.localizedDescription) }
      }
    }.runOnQueue(.main)
    AsyncFunction("getAccountTextActions") { (context: String, promise: Promise) in
      Task { @MainActor in
        do {
          let destination = ProcessingDestination.shared
          guard !destination.computerMode, !ClarifyAudioSession.shared.state.phase.busy, destination.historyContext == context else { throw ComputerFailure.notReady }
          let result = try await CloudAccount.shared.getAccountTextActions(context: context)
          guard !destination.computerMode, !ClarifyAudioSession.shared.state.phase.busy, destination.historyContext == context else { throw CancellationError() }
          promise.resolve(result)
        } catch { promise.reject("TEXT_ERROR", error.localizedDescription) }
      }
    }.runOnQueue(.main)
    AsyncFunction("saveAccountTextActions") { (rows: [[String: Any]], revision: String, lease: String, context: String, promise: Promise) in
      Task { @MainActor in
        do {
          let destination = ProcessingDestination.shared
          guard !destination.computerMode, !ClarifyAudioSession.shared.state.phase.busy, destination.historyContext == context else { throw ComputerFailure.notReady }
          let result = try await CloudAccount.shared.saveAccountTextActions(rows, revision: revision, lease: lease, context: context)
          guard !destination.computerMode, !ClarifyAudioSession.shared.state.phase.busy, destination.historyContext == context else { throw CancellationError() }
          ClarifyAudioSession.shared.libraryChanged()
          promise.resolve(result)
        } catch { promise.reject("TEXT_ERROR", error.localizedDescription) }
      }
    }.runOnQueue(.main)
    AsyncFunction("processTextAction") { (actionID: String, revision: String, text: String, language: String, context: String, promise: Promise) in
      Task { @MainActor in
        do {
          guard TextActionDescriptor.validID(actionID), TextActionDescriptor.wireRevision(revision) != nil else { throw ComputerFailure.invalidResponse }
          promise.resolve(try await ClarifyAudioSession.shared.startText("text_action", text: text, language: language,
            context: context, actionID: actionID, revision: revision))
        } catch { promise.reject("TEXT_ERROR", error.localizedDescription) }
      }
    }.runOnQueue(.main)
    AsyncFunction("accountCommand") { (action: String, value: String, promise: Promise) in
      Task { @MainActor in
        if self.computerScanning { promise.resolve(ProcessingDestination.shared.snapshot()); return }
        if ProcessingDestination.shared.computerMode {
          if action == "auto", !ComputerConnection.shared.busy, ComputerConnection.shared.configured,
             !ClarifyAudioSession.shared.state.phase.busy {
            _ = try? await ProcessingDestination.shared.automaticRefresh(ClarifyAudioSession.shared.library())
          } else if action != "auto" {
            guard !ClarifyAudioSession.shared.state.phase.busy else {
              promise.reject("ACCOUNT_BUSY", L("Finalize o ditado antes de alterar a conta.")); return
            }
            do {
              let previousScope = CloudAccount.shared.scope
              try await ProcessingDestination.shared.authorizeComputerConnection(action, value: value,
                library: ClarifyAudioSession.shared.library())
              if action == "delete", let previousScope { try SharedState()?.discardKeyboardAdditions(scope: previousScope) }
              ClarifyAudioSession.shared.libraryChanged()
            } catch {
              promise.reject("ACCOUNT_ERROR", error.localizedDescription); return
            }
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
    AsyncFunction("copyTextOperationResult") { (operationID: String, context: String) -> Bool in
      guard let text = ClarifyAudioSession.shared.state.textResult(for: operationID, context: context,
        currentContext: ProcessingDestination.shared.historyContext) else { return false }
      // Check ownership and write on the same queue without an await boundary.
      UIPasteboard.general.string = text
      return true
    }.runOnQueue(.main)
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
