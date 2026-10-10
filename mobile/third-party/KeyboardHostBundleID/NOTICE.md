KeyboardHostBundleID

Source: https://github.com/Muskupecli/KeyboardHostBundleID
Commit: f1106dd9f1f09e01c9c28e10e2882990bb14acdc

The Objective-C hook is vendored in native/keyboard. The legacy PKService/XPC resolver is adapted from LegacyHostResolver.swift in the same commit, with exception handling and runtime signature checks. Its MIT license is included here. Clarify uses only fresh captures. The code uses private UIKit APIs and is an experimental TestFlight feature.
