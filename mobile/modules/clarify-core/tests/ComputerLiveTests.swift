import AVFoundation
import CryptoKit
import XCTest
@testable import ClarifyContracts

final class ComputerLiveTests: XCTestCase {
  private let result = ComputerResult(operationID: UUID(), transcript: "hello", text: "hello", rewritten: false, successful: true)

  @MainActor func testBatchesDrainBeforeFinishWithExactDigest() async throws {
    let capture = ComputerLiveCapture()
    let pcm = Data(repeating: 19, count: 2560)
    // Queuing before admission models a slow network without using a microphone.
    for _ in 0..<17 { try capture.append(pcm) }
    capture.end()
    var batches: [Int] = [], sequences: [Int] = []
    var finalBytes = 0, finalHash = "", aborted = false
    capture.start(admit: {}, feed: { sequence, frames in
      sequences.append(sequence); batches.append(frames.count)
      XCTAssertTrue(frames.allSatisfy { $0 == pcm })
    }, finish: { bytes, hash in finalBytes = bytes; finalHash = hash; return self.result }, abort: { aborted = true })
    _ = try await capture.result()
    XCTAssertEqual(batches, [8, 8, 1]); XCTAssertEqual(sequences, [0, 8, 16])
    XCTAssertEqual(finalBytes, 17 * 2560)
    let expected = SHA256.hash(data: Data(repeating: 19, count: 17 * 2560)).map { String(format: "%02x", $0) }.joined()
    XCTAssertEqual(finalHash, expected); XCTAssertFalse(aborted)
  }

  @MainActor func testOverflowAndCancellationNeverFinishOrDropAudio() async throws {
    for overflow in [true, false] {
      let capture = ComputerLiveCapture()
      if overflow {
        for _ in 0..<100 { try capture.append(Data(repeating: 0, count: 2560)) }
        XCTAssertThrowsError(try capture.append(Data(repeating: 0, count: 2)))
      } else { capture.cancel() }
      var finished = false, aborted = false
      capture.start(admit: {}, feed: { _, _ in XCTFail("Retired audio must not be sent") },
        finish: { _, _ in finished = true; return self.result }, abort: { aborted = true })
      do { _ = try await capture.result(); XCTFail("Expected failure") } catch {}
      XCTAssertFalse(finished); XCTAssertTrue(aborted)
    }
  }

  @MainActor func testInFlightBatchRemainsInsidePendingAudioLimit() async throws {
    let capture = ComputerLiveCapture(), pcm = Data(repeating: 0, count: 2560)
    for _ in 0..<8 { try capture.append(pcm) }
    var finished = false
    capture.start(admit: {}, feed: { _, _ in
      // The first eight frames are in flight, so only 92 more fit.
      for _ in 0..<92 { try capture.append(pcm) }
      try capture.append(Data(repeating: 0, count: 2))
    }, finish: { _, _ in finished = true; return self.result }, abort: {})
    do { _ = try await capture.result(); XCTFail("Expected backpressure failure") } catch {}
    XCTAssertFalse(finished)
  }

  @MainActor func testConverterDrainsStereo48kIntoBounded16kFrames() async throws {
    let format = AVAudioFormat(standardFormatWithSampleRate: 48000, channels: 2)!
    let converter = try ComputerLivePCMConverter(format: format)
    let capture = ComputerLiveCapture()
    var suppliedFrames = 0
    // Each callback's input buffer goes out of scope after synchronous conversion.
    for _ in 0..<50 {
      let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 960)!
      buffer.frameLength = 960
      for channel in 0..<2 {
        for i in 0..<960 { buffer.floatChannelData![channel][i] = 0.25 }
      }
      try converter.append(buffer, to: capture); suppliedFrames += 960
    }
    try converter.finish(to: capture)
    var bytes = 0, sizes: [Int] = []
    capture.start(admit: {}, feed: { _, frames in
      for frame in frames { XCTAssertLessThanOrEqual(frame.count, 2560); XCTAssertEqual(frame.count % 2, 0); bytes += frame.count; sizes.append(frame.count) }
    }, finish: { count, _ in XCTAssertEqual(count, bytes); return self.result }, abort: { XCTFail("Unexpected cancellation") })
    _ = try await capture.result()
    XCTAssertTrue(sizes.dropLast().allSatisfy { $0 == 2560 })
    // Converter priming may trim a small boundary; never claim physical capture.
    XCTAssertEqual(Double(bytes) / 2, Double(suppliedFrames) / 3, accuracy: 32)
  }
}
