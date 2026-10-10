import ActivityKit
import SwiftUI
import WidgetKit

@main
struct ClarifyActivity: Widget {
  private func title(_ phase: String, stale: Bool) -> String {
    if stale { return "Abra o Clarify" }
    switch phase {
    case "recording": return "Gravando"
    case "locked": return "Gravação travada"
    case "transcribing": return "Transcrevendo"
    case "rewriting": return "Reescrevendo"
    case "error": return "Confira o Clarify"
    default: return "Microfone ativado"
    }
  }
  var body: some WidgetConfiguration {
    ActivityConfiguration(for: ClarifyActivityAttributes.self) { context in
      HStack(spacing: 12) {
        ClarifyMark().fill(.white).frame(width: 30, height: 30).accessibilityLabel("Clarify")
        VStack(alignment: .leading, spacing: 3) {
          Text("Clarify").font(.headline)
          Text(title(context.state.phase, stale: context.isStale)).font(.subheadline).foregroundStyle(.white.opacity(0.7))
        }
        Spacer()
      }.padding(16).foregroundStyle(.white).activityBackgroundTint(.black).activitySystemActionForegroundColor(.white)
        .widgetURL(URL(string: "clarify://activate"))
    } dynamicIsland: { context in
      DynamicIsland {
        DynamicIslandExpandedRegion(.leading) {
          ClarifyMark().fill(.white).frame(width: 28, height: 28).accessibilityLabel("Clarify")
        }
        DynamicIslandExpandedRegion(.trailing) { Text("Clarify").font(.headline) }
        DynamicIslandExpandedRegion(.bottom) { Text(title(context.state.phase, stale: context.isStale)) }
      } compactLeading: {
        ClarifyMark().fill(.white).frame(width: 20, height: 20).accessibilityLabel("Clarify")
      } compactTrailing: {
        Image(systemName: ["recording", "locked"].contains(context.state.phase) ? "waveform" : "circle.fill")
          .font(.system(size: 12)).foregroundStyle(.white)
      } minimal: {
        ClarifyMark().fill(.white).frame(width: 20, height: 20).accessibilityLabel("Clarify")
      }.widgetURL(URL(string: "clarify://activate")).keylineTint(.white)
    }
  }
}
