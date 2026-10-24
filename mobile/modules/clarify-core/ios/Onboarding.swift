import Foundation

// App-only preference. Credentials remain in the Keychain, outside this state.
struct Onboarding {
  let defaults: UserDefaults
  private let key = "clarify.onboarding.completed"
  init(defaults: UserDefaults = .standard) { self.defaults = defaults }

  func required(signedIn: Bool) -> Bool {
    if defaults.object(forKey: key) == nil {
      // Preserve an existing account's setup. Legacy personal keys do not
      // grant access, even when the earlier setup preference was completed.
      defaults.set(signedIn, forKey: key)
    }
    return !signedIn || !defaults.bool(forKey: key)
  }
  func complete(configured: Bool) throws {
    guard configured else { throw ClarifyError(L("Configure o processamento antes de continuar.")) }
    defaults.set(true, forKey: key)
  }
}
