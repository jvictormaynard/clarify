import AVFoundation
import XCTest
@testable import KeyboardUI

final class MicrophoneFailureTests: XCTestCase {
  func testCallPriorityAndSiriFailuresHaveSpecificRecoveryMessages() {
    let call = NSError(domain: NSOSStatusErrorDomain,
      code: AVAudioSession.ErrorCode.insufficientPriority.rawValue,
      userInfo: [NSLocalizedDescriptionKey: "Session activation failed"])
    XCTAssertEqual(MicrophoneFailure.message(for: call),
      L("O microfone está em uso por uma ligação ou outro aplicativo. Encerre a ligação ou a gravação e tente novamente."))
    let siri = NSError(domain: NSOSStatusErrorDomain,
      code: AVAudioSession.ErrorCode.siriIsRecording.rawValue)
    XCTAssertEqual(MicrophoneFailure.message(for: siri),
      L("A Siri está usando o microfone. Aguarde o término e tente novamente."))
  }
  func testUnknownAudioFailuresDoNotExposeNativeDetailsOrClaimAnActiveCall() {
    let failure = NSError(domain: NSOSStatusErrorDomain, code: -1,
      userInfo: [NSLocalizedDescriptionKey: "internal AVAudioEngine.swift:42"])
    XCTAssertEqual(MicrophoneFailure.message(for: failure),
      L("Não foi possível ativar o microfone. Verifique se há uma ligação ou gravação em outro aplicativo e tente novamente."))
    let unrelated = NSError(domain: "fixture", code: AVAudioSession.ErrorCode.insufficientPriority.rawValue)
    XCTAssertEqual(MicrophoneFailure.message(for: unrelated), MicrophoneFailure.message(for: failure))
  }
  func testIntentionalAppErrorsKeepTheirRecoveryInstructions() {
    XCTAssertEqual(MicrophoneFailure.message(for: ClarifyError("Configure sua chave Groq primeiro.")),
      L("Configure sua chave Groq primeiro."))
  }
}
