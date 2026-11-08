import AVFoundation
import AudioToolbox

enum MicrophoneFailure {
  static func recordingError(for error: Error) -> ClarifyError {
    if let error = error as? ClarifyError { return error }
    let native = error as NSError
    let isFormatFailure = error is AudioClipWriter.Failure ||
      ([NSOSStatusErrorDomain, "com.apple.coreaudio.avfaudio"].contains(native.domain) &&
        [Int(kAudioCodecUnsupportedFormatError), Int(kAudioConverterErr_FormatNotSupported)].contains(native.code))
    if isFormatFailure {
      return ClarifyError(L("Não foi possível iniciar a gravação. Ative o microfone novamente no Clarify."),
        code: "recording_format_unsupported", phase: "recording", status: native.code)
    }
    return ClarifyError(L("Não foi possível gravar o áudio."), code: "recording_failed", phase: "recording")
  }
  static func message(for error: Error) -> String {
    // Preserve intentional app messages, such as a missing Groq key.
    if let error = error as? ClarifyError { return error.localizedDescription }
    let native = error as NSError
    if native.domain == NSOSStatusErrorDomain || native.domain == "com.apple.coreaudio.avfaudio" {
      switch native.code {
      case AVAudioSession.ErrorCode.insufficientPriority.rawValue:
        return L("O microfone está em uso por uma ligação ou outro aplicativo. Encerre a ligação ou a gravação e tente novamente.")
      case AVAudioSession.ErrorCode.siriIsRecording.rawValue:
        return L("A Siri está usando o microfone. Aguarde o término e tente novamente.")
      default: break
      }
    }
    return L("Não foi possível ativar o microfone. Verifique se há uma ligação ou gravação em outro aplicativo e tente novamente.")
  }
}
