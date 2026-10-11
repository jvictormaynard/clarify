// swift-tools-version: 5.9
import PackageDescription
let package = Package(
  name: "ClarifyContracts", platforms: [.macOS(.v13)],
  products: [.library(name: "ClarifyContracts", targets: ["ClarifyContracts"])],
  targets: [
    .target(name: "ClarifyContracts", path: "ios",
      exclude: ["AudioSession.swift", "MicrophoneFailure.swift", "ClarifyCoreModule.swift", "ClarifyCore.podspec", "HapticFeedback.swift", "LiveActivity.swift", "ClarifyActivityAttributes.swift", "ClarifyMark.swift", "ClarifyReturnBridge.h", "ClarifyReturnBridge.m"],
      sources: ["SharedState.swift", "KeyStore.swift", "GroqClient.swift", "RewritePrompt.swift", "KeyboardState.swift", "TypingCorrection.swift", "LocalLibrary.swift", "ActivationRequest.swift", "CloudAccount.swift", "AccountCredential.swift"], linkerSettings: [.linkedLibrary("sqlite3")]),
    .testTarget(name: "ClarifyContractsTests", dependencies: ["ClarifyContracts"], path: "tests")
  ]
)
