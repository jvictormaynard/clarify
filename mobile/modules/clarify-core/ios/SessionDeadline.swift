import Foundation

enum SessionDeadline: Equatable {
  case finishRecording

  static func action(startedAt: Date?, phase: DictationPhase, now: Date) -> Self? {
    if (phase == .recording || phase == .locked), let startedAt,
       now.timeIntervalSince(startedAt) >= 300 { return .finishRecording }
    return nil
  }
}
