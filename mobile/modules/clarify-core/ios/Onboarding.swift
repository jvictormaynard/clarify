import Foundation

// Presentation is separate from authentication and keyboard preparation.
// This app-only preference never contains credentials or account identity.
struct Onboarding {
  let defaults: UserDefaults
  let store: SharedState?
  private let completedKey = "clarify.onboarding.completed"
  private let presentedKey = "clarify.onboarding.presented"
  init(defaults: UserDefaults = .standard, store: SharedState? = SharedState()) { self.defaults = defaults; self.store = store }

  func required(signedIn: Bool) -> Bool {
    if defaults.object(forKey: presentedKey) == nil,
       signedIn || defaults.object(forKey: completedKey) != nil {
      // Existing installations retain their setup, including an unfinished
      // legacy setup. Authentication is checked separately by the route guard.
      defaults.set(true, forKey: presentedKey)
    }
    if defaults.object(forKey: "clarify.textUX.initialized") == nil {
      if defaults.object(forKey: "clarify.textUX.fresh") == nil {
        let existing = signedIn || defaults.object(forKey: presentedKey) != nil ||
          defaults.object(forKey: completedKey) != nil || defaults.object(forKey: "clarify.processing.destination") != nil ||
          defaults.object(forKey: "clarify.account.metadata") != nil ||
          store.map { FileManager.default.fileExists(atPath: $0.root.appendingPathComponent("output-preferences.json").path) } == true
        defaults.set(!existing, forKey: "clarify.textUX.fresh")
      }
      if defaults.bool(forKey: "clarify.textUX.fresh") {
        // Retry a failed first write without treating the welcome screen as an old install.
        guard let store else { return !defaults.bool(forKey: presentedKey) }
        if !FileManager.default.fileExists(atPath: store.root.appendingPathComponent("output-preferences.json").path) {
          do { try store.write(OutputPreferences(style: .natural), to: "output-preferences.json") }
          catch { return !defaults.bool(forKey: presentedKey) }
        }
      }
      defaults.set(true, forKey: "clarify.textUX.initialized")
    }
    return !defaults.bool(forKey: presentedKey)
  }
  func presented() { defaults.set(true, forKey: presentedKey) }
  func complete(configured: Bool) throws {
    guard configured else { throw ClarifyError(L("Configure o processamento antes de continuar.")) }
    defaults.set(true, forKey: completedKey)
    presented()
  }
}
