import XCTest
@testable import ClarifyContracts

final class SessionDeadlineTests: XCTestCase {
  private let origin = Date(timeIntervalSince1970: 1_000)

  func testIdleReadyAndErrorSessionsHaveNoInactivityDeadline() {
    for phase in [DictationPhase.idle, .ready, .error] {
      for interval in [300.0, 3_600, 86_400] {
        XCTAssertNil(SessionDeadline.action(startedAt: nil, phase: phase,
          now: origin.addingTimeInterval(interval)), "Only the user or an OS interruption ends an idle session")
      }
    }
  }
  func testHeldAndLockedClipsKeepTheirFiveMinuteLimit() {
    for phase in [DictationPhase.recording, .locked] {
      XCTAssertNil(SessionDeadline.action(startedAt: origin, phase: phase,
        now: origin.addingTimeInterval(299.9)))
      XCTAssertEqual(SessionDeadline.action(startedAt: origin, phase: phase,
        now: origin.addingTimeInterval(300)), .finishRecording)
    }
  }
  func testProcessingHasNoSessionDeadlineAfterTheClipIsClosed() {
    for phase in [DictationPhase.transcribing, .rewriting] {
      XCTAssertNil(SessionDeadline.action(startedAt: nil, phase: phase,
        now: origin.addingTimeInterval(3_600)))
    }
  }
}
