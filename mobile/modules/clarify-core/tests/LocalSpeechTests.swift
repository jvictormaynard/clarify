#if os(iOS)
import XCTest
@testable import ClarifyContracts

final class LocalSpeechTests: XCTestCase {
  func testAccountOrInstalledAssetsDoNotEnableLocalSpeechWithoutDestinationSupport() {
    for mask in 0..<16 {
      let values = (0..<4).map { mask & (1 << $0) != 0 }
      XCTAssertEqual(LocalSpeechPolicy.canStart(destinationSupportsLocalSpeech: values[0],
        deviceAvailable: values[1], localeSupported: values[2], assetsInstalled: values[3]), mask == 15)
    }
  }
}
#endif
