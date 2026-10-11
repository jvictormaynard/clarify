import ActivityKit

struct ClarifyActivityAttributes: ActivityAttributes {
  struct ContentState: Codable, Hashable {
    var phase: String
  }
}
