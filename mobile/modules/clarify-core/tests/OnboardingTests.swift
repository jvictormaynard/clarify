import XCTest
@testable import ClarifyContracts

final class OnboardingTests: XCTestCase {
  func testFreshProfileRemainsInSetupUntilSuccessfulCompletion() throws {
    let suite = "clarify.test.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    let setup = Onboarding(defaults: defaults)
    XCTAssertTrue(setup.required(existingSetup: false))
    // Saving credentials mid-flow must not complete the flow on a restart.
    XCTAssertTrue(Onboarding(defaults: defaults).required(existingSetup: true))
    XCTAssertThrowsError(try setup.complete(configured: false))
    XCTAssertTrue(setup.required(existingSetup: false))
    try setup.complete(configured: true)
    XCTAssertFalse(Onboarding(defaults: defaults).required(existingSetup: false))
  }
  func testExistingSetupIsPreservedAfterUpgradeAndLogout() {
    let suite = "clarify.test.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    XCTAssertFalse(Onboarding(defaults: defaults).required(existingSetup: true))
    XCTAssertFalse(Onboarding(defaults: defaults).required(existingSetup: false))
  }
}
