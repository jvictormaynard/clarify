import AVFoundation
import XCTest
@testable import ClarifyContracts

final class AudioClipTests: XCTestCase {
  func testFailedCreationLeavesNoPartialClipOrUnrelatedDeletion() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    let neighbour = root.appendingPathComponent("keep.txt")
    try Data("keep".utf8).write(to: neighbour)
    let format = try XCTUnwrap(AVAudioFormat(standardFormatWithSampleRate: 48_000, channels: 1))
    let unsupported = root.appendingPathComponent("clip.unsupported")
    XCTAssertThrowsError(try AudioClipWriter(url: unsupported, inputFormat: format))
    XCTAssertFalse(FileManager.default.fileExists(atPath: unsupported.path))
    XCTAssertEqual(try Data(contentsOf: neighbour), Data("keep".utf8))
  }
  func testRouteFormatMismatchAndClosedWriterRejectNewBuffers() throws {
    let url = FileManager.default.temporaryDirectory.appendingPathComponent("\(UUID().uuidString).m4a")
    defer { try? FileManager.default.removeItem(at: url) }
    let format = try XCTUnwrap(AVAudioFormat(standardFormatWithSampleRate: 48_000, channels: 1))
    let other = try XCTUnwrap(AVAudioFormat(standardFormatWithSampleRate: 16_000, channels: 1))
    let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: other, frameCapacity: 10))
    buffer.frameLength = 10
    let writer = try AudioClipWriter(url: url, inputFormat: format)
    XCTAssertThrowsError(try writer.write(buffer)) { error in
      guard case AudioClipWriter.Failure.formatChanged = error else { return XCTFail("Unexpected error: \(error)") }
    }
    writer.cancel()
    XCTAssertNoThrow(try writer.finish())
    XCTAssertThrowsError(try writer.write(buffer)) { error in
      guard case AudioClipWriter.Failure.closed = error else { return XCTFail("Unexpected error: \(error)") }
    }
  }
  func testNativeFormatsProduceReadableMonoAACWithSpeechAndCompleteDuration() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    for rate in [8_000.0, 16_000, 24_000, 44_100, 48_000, 96_000, 192_000] {
      for channels in [AVAudioChannelCount(1), 2] {
        let input = try XCTUnwrap(AVAudioFormat(standardFormatWithSampleRate: rate, channels: channels))
        let url = root.appendingPathComponent("\(Int(rate))-\(channels).m4a")
        do {
          let writer = try AudioClipWriter(url: url, inputFormat: input)
          // Uneven chunks exercise streaming conversion and its final tail.
          let total = AVAudioFrameCount(rate * 0.7)
          var position: AVAudioFrameCount = 0
          while position < total {
            let count = min(997, total - position)
            let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: input, frameCapacity: count))
            buffer.frameLength = count
            for channel in 0..<Int(channels) {
              for frame in 0..<Int(count) {
                buffer.floatChannelData![channel][frame] = Float(0.2 * sin(2 * .pi * 440 * Double(position + AVAudioFrameCount(frame)) / rate))
              }
            }
            try writer.write(buffer)
            position += count
          }
          try writer.finish()
          let saved = try AVAudioFile(forReading: url)
          XCTAssertEqual(saved.fileFormat.streamDescription.pointee.mFormatID, kAudioFormatMPEG4AAC)
          XCTAssertEqual(saved.processingFormat.sampleRate, 24_000, "input \(rate) / \(channels)")
          XCTAssertEqual(saved.processingFormat.channelCount, 1, "input \(rate) / \(channels)")
          XCTAssertEqual(Double(saved.length) / saved.processingFormat.sampleRate, 0.7, accuracy: 0.035)
          let decoded = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: saved.processingFormat, frameCapacity: AVAudioFrameCount(saved.length)))
          try saved.read(into: decoded)
          let start = Int(decoded.frameLength) / 4
          let end = Int(decoded.frameLength) * 3 / 4
          let energy = (start..<end).reduce(0.0) { $0 + pow(Double(decoded.floatChannelData![0][$1]), 2) }
          XCTAssertGreaterThan(sqrt(energy / Double(end - start)), 0.08, "input \(rate) / \(channels)")
          let bytes = try FileManager.default.attributesOfItem(atPath: url.path)[.size] as? NSNumber
          XCTAssertLessThan(try XCTUnwrap(bytes).intValue, 32_000)
        } catch {
          XCTFail("input \(rate) / \(channels): \(error)")
        }
      }
    }
  }
}
