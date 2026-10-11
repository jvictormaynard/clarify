import Foundation

// App-only preference. Credentials remain in the Keychain, outside this state.
struct Onboarding {
  let defaults: UserDefaults
  private let key = "clarify.onboarding.completed"
  init(defaults: UserDefaults = .standard) { self.defaults = defaults }

  func required(existingSetup: Bool) -> Bool {
    if defaults.object(forKey: key) == nil {
      // Resolve migration once, before the new first-run flow can save a key.
      defaults.set(existingSetup, forKey: key)
    }
    return !defaults.bool(forKey: key)
  }
  func complete(configured: Bool) throws {
    guard configured else { throw ClarifyError("Configure o processamento antes de continuar.") }
    defaults.set(true, forKey: key)
  }
}
