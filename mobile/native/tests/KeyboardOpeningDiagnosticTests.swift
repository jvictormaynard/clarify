import XCTest
import UIKit
@testable import KeyboardUI

final class KeyboardOpeningDiagnosticTests: XCTestCase {
  private func report() -> KeyboardOpeningReport {
    KeyboardOpeningReport(ios: "26.6.2", appVersion: "test", appBuild: "0",
      keyboardLabel: "Clarify", screenWidth: 402, screenHeight: 874)
  }
  func testExportRetainsAOneFrameOvershootEvenWhenFinalHeightIsCorrect() throws {
    var report = report()
    for (index, height) in [34.0, 598, 370, 370].enumerated() {
      XCTAssertTrue(report.append(.init(elapsed: Double(index) / 120, opening: 1,
        phase: "opening", guideHeight: height, composerHeight: height)))
    }
    report.completeOpening(1)
    report.outcome = "completed"
    let object = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(report)) as? [String: Any])
    let openings = try XCTUnwrap(object["openings"] as? [[String: Any]])
    XCTAssertEqual(openings.first?["peakGuideHeight"] as? Double, 598)
    XCTAssertEqual(openings.first?["settledGuideHeight"] as? Double, 370)
    XCTAssertEqual((object["frames"] as? [Any])?.count, 4)
    XCTAssertEqual(object["keyboardLabel"] as? String, "Clarify")
  }
  func testClosingFramesDoNotPolluteTheOpeningSummaryAndInvalidSamplesAreRejected() {
    var report = report()
    XCTAssertFalse(report.append(.init(elapsed: .nan, opening: 1, phase: "opening", guideHeight: 370, composerHeight: 370)))
    XCTAssertTrue(report.append(.init(elapsed: 0, opening: 1, phase: "opening", guideHeight: 370, composerHeight: 370)))
    XCTAssertTrue(report.append(.init(elapsed: 1, opening: 1, phase: "closing", guideHeight: 34, composerHeight: 34)))
    report.completeOpening(1)
    XCTAssertEqual(report.openings.first?.settledGuideHeight, 370)
  }
  func testDiagnosticScreenUsesAnOrdinaryComposerAndDoesNotStartAnAutomaticRun() async throws {
    try await MainActor.run {
      let screen = KeyboardOpeningDiagnostic(); screen.loadViewIfNeeded()
      func fields(_ view: UIView) -> [UITextField] {
        (view as? UITextField).map { [$0] } ?? view.subviews.flatMap(fields)
      }
      let field = try XCTUnwrap(fields(screen.view).first)
      XCTAssertFalse(field.isSecureTextEntry)
      XCTAssertEqual(field.keyboardType, .default)
      XCTAssertNil(screen.report, "Measurement requires an explicit user action")
      XCTAssertFalse(field.isFirstResponder, "Opening the screen must not select a keyboard")
    }
  }
}
