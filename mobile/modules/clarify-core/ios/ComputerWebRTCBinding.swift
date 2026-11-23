import Foundation
import CryptoKit

struct ComputerWebRTCBinding: Codable, Equatable {
  let signal_url: String
  let public_key: [String: String]
  static var configuredURL: String? {
    guard let raw = Bundle.main.object(forInfoDictionaryKey: "ClarifyWebRTCSignalURL") as? String,
      let url = URLComponents(string: raw), url.scheme == "https", url.host != nil,
      url.user == nil, url.password == nil, url.query == nil, url.fragment == nil,
      url.path == "/signal" else { return nil }
    return raw
  }
  func validate() throws {
    guard signal_url == Self.configuredURL, Set(public_key.keys) == ["kty", "crv", "x", "y"],
      public_key["kty"] == "EC", public_key["crv"] == "P-256",
      let x = public_key["x"].flatMap({ ComputerInvitation.base64URL($0, bytes: 32) }),
      let y = public_key["y"].flatMap({ ComputerInvitation.base64URL($0, bytes: 32) }),
      (try? P256.Signing.PublicKey(x963Representation: Data([4]) + x + y)) != nil else {
      throw ComputerFailure.invalidResponse
    }
  }
}
