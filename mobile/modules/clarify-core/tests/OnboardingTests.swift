import XCTest
@testable import ClarifyContracts

final class OnboardingTests: XCTestCase {
  func testFreshProfileRemainsInSetupUntilSuccessfulCompletion() throws {
    let suite = "clarify.test.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    let setup = Onboarding(defaults: defaults)
    XCTAssertTrue(setup.required(signedIn: false))
    // Saving credentials mid-flow must not complete the flow on a restart.
    XCTAssertTrue(Onboarding(defaults: defaults).required(signedIn: true))
    XCTAssertThrowsError(try setup.complete(configured: false))
    XCTAssertTrue(setup.required(signedIn: false))
    try setup.complete(configured: true)
    XCTAssertFalse(Onboarding(defaults: defaults).required(signedIn: true))
    XCTAssertTrue(Onboarding(defaults: defaults).required(signedIn: false))
  }
  func testExistingAccountNeedsSignInAgainAfterLogoutWithoutRepeatingSetup() {
    let suite = "clarify.test.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    XCTAssertFalse(Onboarding(defaults: defaults).required(signedIn: true))
    XCTAssertTrue(Onboarding(defaults: defaults).required(signedIn: false))
    XCTAssertFalse(Onboarding(defaults: defaults).required(signedIn: true))
  }
  func testCompletedLegacyKeySetupStillRequiresAnAccount() {
    let suite = "clarify.test.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    defaults.set(true, forKey: "clarify.onboarding.completed")
    XCTAssertTrue(Onboarding(defaults: defaults).required(signedIn: false))
    XCTAssertTrue(defaults.bool(forKey: "clarify.onboarding.completed"))
  }
}
