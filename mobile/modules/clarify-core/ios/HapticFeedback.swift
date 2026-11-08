import UIKit

// Use the standard generators without tying delivery to the extension's remote
// window. A light impact marks typing; a medium impact marks recording actions.
final class HapticFeedback {
  private let key: UIImpactFeedbackGenerator
  private let recording: UIImpactFeedbackGenerator

  init(key: UIImpactFeedbackGenerator = UIImpactFeedbackGenerator(style: .light),
       recording: UIImpactFeedbackGenerator = UIImpactFeedbackGenerator(style: .medium)) {
    self.key = key
    self.recording = recording
  }
  func prepare() { key.prepare(); recording.prepare() }
  func type() { key.impactOccurred(); key.prepare() }
  func record(_ action: String) {
    guard ["start", "lock", "finish"].contains(action) else { return }
    recording.impactOccurred()
    recording.prepare()
  }
}
