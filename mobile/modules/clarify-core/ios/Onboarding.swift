import Foundation

// Presentation is separate from authentication and keyboard preparation.
// This app-only preference never contains credentials or account identity.
struct Onboarding {
  let defaults: UserDefaults
  private let completedKey = "clarify.onboarding.completed"
  private let presentedKey = "clarify.onboarding.presented"
  init(defaults: UserDefaults = .standard) { self.defaults = defaults }

  func required(signedIn: Bool) -> Bool {
    if defaults.object(forKey: presentedKey) == nil,
       signedIn || defaults.object(forKey: completedKey) != nil {
      // Existing installations retain their setup, including an unfinished
      // legacy setup. Authentication is checked separately by the route guard.
      defaults.set(true, forKey: presentedKey)
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
