import AVFoundation
import XCTest
@testable import KeyboardUI

final class MicrophoneFailureTests: XCTestCase {
  func testRecordingFormatFailureDoesNotExposeAppleDiagnostics() {
    let native = NSError(domain: "com.apple.coreaudio.avfaudio", code: 560226676,
      userInfo: [NSLocalizedDescriptionKey: "The operation couldn’t be completed. (com.apple.coreaudio.avfaudio error 560226676.)"])
    let failure = MicrophoneFailure.recordingError(for: native)
    XCTAssertEqual(failure.localizedDescription, L("Não foi possível iniciar a gravação. Ative o microfone novamente no Clarify."))
    XCTAssertEqual(failure.code, "recording_format_unsupported")
    XCTAssertEqual(failure.phase, "recording")
    XCTAssertEqual(failure.status, 560226676)
  }
  func testRecordingErrorsKeepIntentionalMessagesAndHideUnknownNativeDetails() {
    let intentional = ClarifyError("Entre na sua conta primeiro.", code: "authentication_required")
    XCTAssertEqual(MicrophoneFailure.recordingError(for: intentional).code, "authentication_required")
    XCTAssertEqual(MicrophoneFailure.recordingError(for: intentional).localizedDescription, intentional.localizedDescription)
    let unknown = NSError(domain: "fixture", code: 560226676,
      userInfo: [NSLocalizedDescriptionKey: "private path /private/recording.m4a"])
    XCTAssertEqual(MicrophoneFailure.recordingError(for: unknown).localizedDescription,
      L("Não foi possível gravar o áudio."))
    XCTAssertEqual(MicrophoneFailure.recordingError(for: unknown).code, "recording_failed")
  }
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
