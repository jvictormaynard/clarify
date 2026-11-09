import Foundation

// Lab output has no account, destination or history effects. Remote refreshes
// are diagnostic context, not a reason to exclude an independent local test.
struct AppleLabAdmission {
  var active = true
  var labBusy = false
  var privateBusy = false
  var scanning = false
  var phase: DictationPhase = .idle
  var remoteBusy = false

  var blockReason: String? {
    if !active { return "app_inactive" }
    if labBusy { return "apple_test_busy" }
    if privateBusy { return "private_session_busy" }
    if scanning { return "scanner_open" }
    if phase.busy { return "dictation_busy" }
    return nil
  }
  var snapshot: [String: Any] {
    ["active": active, "labBusy": labBusy, "privateSessionBusy": privateBusy,
      "scannerOpen": scanning, "dictationPhase": phase.rawValue,
      "remoteBusy": remoteBusy, "remoteBusyBlocksLab": false,
      "blockedBy": blockReason ?? "none"]
  }
}
