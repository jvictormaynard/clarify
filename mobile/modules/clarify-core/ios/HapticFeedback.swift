import UIKit

// Use the standard generators without tying delivery to the extension's remote
// window. A light impact marks typing; a medium impact marks recording actions.
final class HapticFeedback {
  private let key: UIImpactFeedbackGenerator
  private let recording: UIImpactFeedbackGenerator
  private let inputClick: () -> Void

  init(key: UIImpactFeedbackGenerator = UIImpactFeedbackGenerator(style: .light),
       recording: UIImpactFeedbackGenerator = UIImpactFeedbackGenerator(style: .medium),
       inputClick: @escaping () -> Void = { UIDevice.current.playInputClick() }) {
    self.key = key
    self.recording = recording
    self.inputClick = inputClick
  }
  func prepare() { key.prepare(); recording.prepare() }
  func type() { key.impactOccurred(); key.prepare() }
  // UIKit applies the keyboard-click setting and input-view visibility.
  func pressKey() { inputClick(); type() }
  func record(_ action: String) {
    guard ["start", "lock", "finish"].contains(action) else { return }
    recording.impactOccurred()
    recording.prepare()
  }
}
