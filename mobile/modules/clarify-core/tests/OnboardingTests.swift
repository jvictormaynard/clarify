import XCTest
@testable import ClarifyContracts

final class OnboardingTests: XCTestCase {
  private func withDefaults(_ test: (UserDefaults) throws -> Void) rethrows {
    let suite = "clarify.test.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    try test(defaults)
  }

  func testFreshInstallShowsOnceEvenWhenSetupIsSkipped() {
    withDefaults { defaults in
      let setup = Onboarding(defaults: defaults)
      XCTAssertTrue(setup.required(signedIn: false))
      // Reading readiness is not proof that a screen reached the user.
      XCTAssertTrue(Onboarding(defaults: defaults).required(signedIn: false))
      setup.presented()
      XCTAssertFalse(Onboarding(defaults: defaults).required(signedIn: false))
      XCTAssertFalse(Onboarding(defaults: defaults).required(signedIn: true))
      XCTAssertFalse(Onboarding(defaults: defaults).required(signedIn: false))
    }
  }

  func testExistingAccountsDoNotSeeGeneralOnboardingAfterUpgradeOrLogout() {
    withDefaults { defaults in
      XCTAssertFalse(Onboarding(defaults: defaults).required(signedIn: true))
      XCTAssertFalse(Onboarding(defaults: defaults).required(signedIn: false))
    }
  }

  func testExistingSetupPreferencesDoNotPresentAgainAfterUpgrade() {
    for completed in [true, false] {
      withDefaults { defaults in
        defaults.set(completed, forKey: "clarify.onboarding.completed")
        XCTAssertFalse(Onboarding(defaults: defaults).required(signedIn: false))
        XCTAssertEqual(defaults.bool(forKey: "clarify.onboarding.completed"), completed)
      }
    }
  }

  func testCompletionStillRequiresAConfiguredAccount() throws {
    try withDefaults { defaults in
      let setup = Onboarding(defaults: defaults)
      XCTAssertThrowsError(try setup.complete(configured: false))
      XCTAssertTrue(setup.required(signedIn: false))
      try setup.complete(configured: true)
      XCTAssertTrue(defaults.bool(forKey: "clarify.onboarding.completed"))
      XCTAssertFalse(Onboarding(defaults: defaults).required(signedIn: false))
    }
  }
}
