import Foundation

enum SessionDeadline: Equatable {
  case finishRecording, deactivate

  static func action(startedAt: Date?, idleSince: Date, phase: DictationPhase, now: Date) -> Self? {
    if let startedAt, now.timeIntervalSince(startedAt) >= 300 { return .finishRecording }
    if !phase.busy && now.timeIntervalSince(idleSince) >= 300 { return .deactivate }
    return nil
  }
}
