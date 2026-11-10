import UIKit

// App-only preference. Transcription identity and output preferences are frozen
// by AudioSession; this setting never grants processing or account authority.
enum AppleDictationPreference {
  static let key = "clarify.dictation.appleReview"
  static var enabled: Bool { UserDefaults.standard.bool(forKey: key) }
}
@MainActor enum AppleDictation {
  static var available: Bool {
    if #available(iOS 26.0, *) { return UIWritingToolsCoordinator.isWritingToolsAvailable }
    return false
  }
  static func snapshot() -> [String: Any] {
    ["enabled": AppleDictationPreference.enabled, "available": available,
      "message": L(available ? "Dictate in Clarify and review Apple's result before returning to the keyboard." :
        "Apple rewriting requires iOS 26 and available Apple Intelligence Writing Tools.")]
  }
  static func setEnabled(_ value: Bool) throws -> [String: Any] {
    guard !ClarifyAudioSession.shared.state.phase.busy, !ClarifyPrivateWritingToolsBridge.isBusy(), !busy else {
      throw ClarifyError(L("Wait for the operation to finish before changing Apple rewriting."))
    }
    if value {
      let destination = ProcessingDestination.shared
      try validate(preferences: SharedState()?.outputPreferences() ?? OutputPreferences(),
        policy: DictationPolicyStore().read(scope: destination.historyScope ?? ""))
    }
    UserDefaults.standard.set(value, forKey: AppleDictationPreference.key)
    if !value, ClarifyAudioSession.shared.state.errorCode == "apple_dictation_foreground" {
      ClarifyAudioSession.shared.clearResult()
    }
    return snapshot()
  }
  static func validate(preferences: OutputPreferences, policy: DictationPolicy) throws {
    guard available else { throw ClarifyError(L("Apple rewriting requires iOS 26 and available Apple Intelligence Writing Tools.")) }
    guard [.default, .formal, .casual].contains(preferences.style) else {
      throw ClarifyError(L("Choose Default, Formal or Casual in Output settings for Apple rewriting."))
    }
    guard [.legacy, .natural].contains(policy.mode) else {
      throw ClarifyError(L("Choose Natural dictation mode in Output settings for Apple rewriting."))
    }
    let capabilities = ProcessingDestination.shared.processingCapabilities
    guard capabilities.explicitPolicy, capabilities.supports("cleanup_levels", "preserve") else {
      throw ClarifyError(L("Refresh the transcription destination. Apple rewriting requires transcription without server rewriting."))
    }
  }

  private final class Pending {
    let id: String
    let continuation: CheckedContinuation<String, Error>
    var navigation: UINavigationController?
    var observer: NSObjectProtocol?
    init(id: String, continuation: CheckedContinuation<String, Error>) {
      self.id = id; self.continuation = continuation
    }
  }
  private static var pending: Pending?
  static var busy: Bool { pending != nil }

  static func review(_ source: String, preferences: OutputPreferences, operationID: String) async throws -> String {
    try Task.checkCancellation()
    guard available, UIApplication.shared.applicationState == .active,
      !source.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
      source.utf8.count <= AppleRewriteEngine.maxInputBytes else {
      throw ClarifyError(L("Apple review could not open. The transcript was preserved. Keep Clarify open and use a shorter recording."))
    }
    guard !busy, !ClarifyPrivateWritingToolsBridge.isBusy() else { throw ClarifyError(L("Close the current Apple editor before starting another review.")) }
    return try await withTaskCancellationHandler(operation: {
      try await withCheckedThrowingContinuation { continuation in
        guard !Task.isCancelled else { continuation.resume(throwing: CancellationError()); return }
        guard let presenter = presenter(), presenter.presentedViewController == nil else {
          continuation.resume(throwing: ClarifyError(L("Close the current sheet before starting Apple review."))); return
        }
        let owner = Pending(id: operationID, continuation: continuation)
        pending = owner
        let editor = AppleWritingToolsController(source: source, target: preferences.language.rawValue,
          privateStyle: preferences.style.rawValue, useResult: { [weak owner] text in
            guard let owner, pending === owner else { return }
            if let text { finish(owner, result: .success(text)) }
            else { finish(owner, result: .failure(ClarifyError(L("Apple review was cancelled. The transcript was preserved.")))) }
          })
        let navigation = UINavigationController(rootViewController: editor)
        navigation.isModalInPresentation = true
        owner.navigation = navigation
        owner.observer = NotificationCenter.default.addObserver(forName: UIApplication.didEnterBackgroundNotification,
          object: nil, queue: .main) { _ in
            Task { @MainActor in
              guard pending === owner else { return }
              finish(owner, result: .failure(ClarifyError(L("Apple review stopped when Clarify closed. The transcript was preserved."))))
            }
          }
        presenter.present(navigation, animated: true) {
          // Cancellation can arrive during the presentation transition.
          if pending !== owner, presenter.presentedViewController === navigation {
            presenter.dismiss(animated: true)
          }
        }
      }
    }, onCancel: { Task { @MainActor in cancel(operationID) } })
  }
  static func cancel(_ id: String?) {
    guard let owner = pending, id == nil || owner.id == id else { return }
    finish(owner, result: .failure(CancellationError()))
  }
  static func stopForAudioInterruption(_ id: String?) -> Bool {
    guard let owner = pending, owner.id == id else { return false }
    finish(owner, result: .failure(ClarifyError(L("Apple review stopped after an audio interruption. The transcript was preserved."))))
    return true
  }
  private static func finish(_ owner: Pending, result: Result<String, Error>) {
    guard pending === owner else { return }
    pending = nil
    if let observer = owner.observer { NotificationCenter.default.removeObserver(observer) }
    owner.observer = nil
    let navigation = owner.navigation
    owner.navigation = nil
    // The editor requests verified responder teardown when its view disappears.
    if let navigation, let presenter = navigation.presentingViewController,
      presenter.presentedViewController === navigation {
      // Dismiss the owned root from its presenter, including a translation sheet
      // above it. Dismissing navigation itself can close only that child sheet.
      presenter.dismiss(animated: true)
    }
    owner.continuation.resume(with: result)
  }
  private static func presenter() -> UIViewController? {
    let window = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
      .filter { $0.activationState == .foregroundActive }.flatMap(\.windows).first { $0.isKeyWindow }
    @MainActor func top(_ controller: UIViewController?) -> UIViewController? {
      if let shown = controller?.presentedViewController { return top(shown) }
      if let navigation = controller as? UINavigationController { return top(navigation.visibleViewController) }
      if let tabs = controller as? UITabBarController { return top(tabs.selectedViewController) }
      return controller
    }
    return top(window?.rootViewController)
  }
}
