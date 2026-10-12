import UIKit

// No microphone or provider in this fixture. It exercises only the real
// keyboard URL, nonce consumption and the real native return bridge.
@main
final class ActivationFixtureApp: UIResponder, UIApplicationDelegate {
  func application(_ app: UIApplication, open url: URL, options: [UIApplication.OpenURLOptionsKey: Any] = [:]) -> Bool {
    NotificationCenter.default.post(name: .init("ClarifyFixtureURL"), object: url,
      userInfo: ["source": options[.sourceApplication] as? String ?? "unknown"])
    return true
  }
}

final class ActivationFixtureScene: UIResponder, UIWindowSceneDelegate {
  var window: UIWindow?
  private var pending: URL?
  private var opener: String?
  private var events: [String] = []
  private func event(_ value: String) {
    events.append(value + ":" + String(UIApplication.shared.applicationState.rawValue))
    try? SharedState()?.write(events, to: "container-events.json")
    NSLog("ClarifyFixtureContainer %@", events.last ?? value)
  }
  func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options: UIScene.ConnectionOptions) {
    guard let scene = scene as? UIWindowScene else { return }
    let window = UIWindow(windowScene: scene); window.rootViewController = UIViewController()
    window.rootViewController?.view.backgroundColor = .systemBackground
    window.makeKeyAndVisible(); self.window = window
    NotificationCenter.default.addObserver(self, selector: #selector(returnToSource), name: UIApplication.didBecomeActiveNotification, object: nil)
    NotificationCenter.default.addObserver(self, selector: #selector(receiveDelegateURL), name: .init("ClarifyFixtureURL"), object: nil)
    event("connected")
    if let store = SharedState() { try? store.write(["ready": true], to: "container-ready.json") }
    pending = options.urlContexts.first?.url
    opener = options.urlContexts.first?.options.sourceApplication
  }
  func scene(_ scene: UIScene, openURLContexts contexts: Set<UIOpenURLContext>) {
    event("received-url")
    pending = contexts.first?.url; opener = contexts.first?.options.sourceApplication; returnToSource()
  }
  func sceneDidBecomeActive(_ scene: UIScene) { event("scene-active"); returnToSource() }
  @objc private func receiveDelegateURL(_ notification: Notification) {
    event("delegate-url"); pending = notification.object as? URL
    opener = notification.userInfo?["source"] as? String; returnToSource()
  }
  @objc private func returnToSource() {
    guard pending != nil else { return }
    Task { @MainActor in
      let deadline = ContinuousClock.now.advanced(by: .seconds(2))
      while UIApplication.shared.applicationState == .inactive, ContinuousClock.now < deadline {
        do { try await Task.sleep(nanoseconds: 20_000_000) } catch { return }
      }
      self.event("return-attempt")
      guard UIApplication.shared.applicationState == .active, let url = self.pending else { return }
      pending = nil
      let token = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first { $0.name == "token" }?.value
      let store = SharedState(), request = token.flatMap { store?.consumeActivation($0) }
      var diagnostic: [String: Any] = request == nil ? [:] : ClarifyReturnDiagnostics() as? [String: Any] ?? [:]
      diagnostic["nonceConsumed"] = request != nil
      diagnostic["source"] = request?.sourceBundleID ?? "unknown"
      diagnostic["systemSource"] = opener ?? "unknown"
      diagnostic["opened"] = request != nil && ClarifyReturnBridge.openSource(bundleID: request?.sourceBundleID)
      if let store { try? store.write(diagnostic.mapValues { String(describing: $0) }, to: "return-trace.json") }
    }
  }
}
