import ActivityKit
import UIKit

// One local activity for the active microphone session. No push tokens or text.
final class ClarifyLiveActivity {
  private var activity: Activity<ClarifyActivityAttributes>?
  private var lastPhase: String?
  private var lastUpdate = Date.distantPast
  private var pending: Task<Void, Never>?
  private var attempted = false

  init() {
    let abandoned = Activity<ClarifyActivityAttributes>.activities
    Task { for item in abandoned { await item.end(nil, dismissalPolicy: .immediate) } }
  }
  func update(_ state: DictationSnapshot) {
    guard state.sessionActive else {
      attempted = false; lastPhase = nil
      if let current = activity {
        activity = nil
        let previous = pending
        pending = Task { await previous?.value; await current.end(nil, dismissalPolicy: .immediate) }
      }
      return
    }
    let phase = state.phase.rawValue
    let content = ActivityContent(state: ClarifyActivityAttributes.ContentState(phase: phase),
      staleDate: Date().addingTimeInterval(310))
    if activity == nil, !attempted, UIApplication.shared.applicationState == .active {
      attempted = true
      guard ActivityAuthorizationInfo().areActivitiesEnabled else { return }
      activity = try? Activity.request(attributes: ClarifyActivityAttributes(), content: content, pushType: nil)
      lastPhase = activity == nil ? nil : phase
      lastUpdate = Date()
    } else if let current = activity, lastPhase != phase || Date().timeIntervalSince(lastUpdate) >= 60 {
      lastPhase = phase
      lastUpdate = Date()
      let previous = pending
      pending = Task { await previous?.value; await current.update(content) }
    }
  }
}
