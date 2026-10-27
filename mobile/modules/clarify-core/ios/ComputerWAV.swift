import Foundation

enum ComputerWAV {
  static let maximumSamples = 16_000 * 300
  static func wrapPCM16(_ pcm: Data) throws -> Data {
    guard !pcm.isEmpty, pcm.count % 2 == 0, pcm.count <= maximumSamples * 2 else { throw ComputerFailure.invalidAudio }
    var result = Data()
    func ascii(_ text: String) { result.append(Data(text.utf8)) }
    func number<T: FixedWidthInteger>(_ value: T) { var little = value.littleEndian; withUnsafeBytes(of: &little) { result.append(contentsOf: $0) } }
    ascii("RIFF"); number(UInt32(36 + pcm.count)); ascii("WAVEfmt "); number(UInt32(16))
    number(UInt16(1)); number(UInt16(1)); number(UInt32(16_000)); number(UInt32(32_000)); number(UInt16(2)); number(UInt16(16))
    ascii("data"); number(UInt32(pcm.count)); result.append(pcm)
    return result
  }
  static func validate(_ data: Data) throws {
    guard data.count > 44, data.count <= maximumSamples * 2 + 44 else { throw ComputerFailure.invalidAudio }
    // The converter emits this single PCM chunk format. Compare the complete
    // header, including the declared length, before the upload boundary.
    let expected = try wrapPCM16(Data(data.dropFirst(44)))
    guard data.prefix(44) == expected.prefix(44) else { throw ComputerFailure.invalidAudio }
  }
}
