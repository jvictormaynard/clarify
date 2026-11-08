import AVFoundation
import Foundation
import XCTest
@testable import ClarifyContracts

final class ComputerAudioTests: XCTestCase {
  private func writePCM(_ url: URL, rate: Double, channels: AVAudioChannelCount, frames: Int) throws {
    let format = try XCTUnwrap(AVAudioFormat(standardFormatWithSampleRate: rate, channels: channels))
    let file = try AVAudioFile(forWriting: url, settings: format.settings)
    let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 4096))
    var offset = 0
    while offset < frames {
      let count = min(4096, frames - offset)
      buffer.frameLength = AVAudioFrameCount(count)
      for channel in 0..<Int(channels) {
        for frame in 0..<count {
          buffer.floatChannelData![channel][frame] = Float(sin(Double(offset + frame) * 2 * .pi * 440 / rate)) * 0.25
        }
      }
      try file.write(from: buffer)
      offset += count
    }
  }

  func testPCMConversionPreservesDurationAndFinalSignalAcrossPartialBuffers() async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    for (index, fixture) in [(8000.0, 1, 167), (44100.0, 2, 44237), (96000.0, 1, 28903)].enumerated() {
      let (rate, channels, frames) = fixture
      let source = root.appendingPathComponent("source-\(index).caf")
      try writePCM(source, rate: rate, channels: AVAudioChannelCount(channels), frames: frames)
      let wav = try await ComputerAudio.convert(source)
      let output = root.appendingPathComponent("converted-\(index).wav")
      try wav.write(to: output)
      // AVAudioFile independently parses the returned WAV and its PCM samples.
      let file = try AVAudioFile(forReading: output)
      XCTAssertEqual(file.fileFormat.commonFormat, .pcmFormatInt16)
      XCTAssertEqual(file.fileFormat.sampleRate, 16000)
      XCTAssertEqual(file.fileFormat.channelCount, 1)
      let expectedFrames = Int((Double(frames) * 16000 / rate).rounded())
      XCTAssertLessThanOrEqual(abs(Int(file.length) - expectedFrames), 64)
      let decoded = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: AVAudioFrameCount(file.length)))
      try file.read(into: decoded)
      let samples = try XCTUnwrap(decoded.floatChannelData?[0])
      let end = Int(decoded.frameLength), count = min(800, end)
      XCTAssertGreaterThan(count, 0)
      let energy = ((end - count)..<end).reduce(0.0) { $0 + Double(samples[$1]) * Double(samples[$1]) } / Double(count)
      XCTAssertGreaterThan(energy, 0.005, "The final audio must not be lost or replaced with silence")
    }
  }

  func testConversionCapsPermittedPaddingAndRejectsInputAbove301Seconds() async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    let padded = root.appendingPathComponent("padded.caf")
    try writePCM(padded, rate: 16000, channels: 1, frames: 4_804_000)
    let wav = try await ComputerAudio.convert(padded)
    XCTAssertEqual(wav.count, 9_600_044)
    let output = root.appendingPathComponent("capped.wav")
    try wav.write(to: output)
    let file = try AVAudioFile(forReading: output)
    XCTAssertEqual(file.length, 4_800_000)
    let oversized = root.appendingPathComponent("oversized.caf")
    try writePCM(oversized, rate: 16000, channels: 1, frames: 4_816_160)
    do {
      _ = try await ComputerAudio.convert(oversized)
      XCTFail("Input above 301 seconds must be rejected")
    } catch { XCTAssertEqual(error as? ComputerFailure, .invalidAudio) }
  }
}
