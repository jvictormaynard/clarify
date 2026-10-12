import UIKit

// No microphone or provider in this fixture. It exercises only the real
// keyboard URL, nonce consumption and the real native return bridge.
@main
final class ActivationFixtureApp: UIResponder, UIApplicationDelegate {}

final class ActivationFixtureScene: UIResponder, UIWindowSceneDelegate {
  var window: UIWindow?
  private var pending: URL?
  private var opener: String?
  func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options: UIScene.ConnectionOptions) {
    guard let scene = scene as? UIWindowScene else { return }
    let window = UIWindow(windowScene: scene); window.rootViewController = UIViewController()
    window.rootViewController?.view.backgroundColor = .systemBackground
    window.makeKeyAndVisible(); self.window = window
    NotificationCenter.default.addObserver(self, selector: #selector(returnToSource), name: UIApplication.didBecomeActiveNotification, object: nil)
    if let store = SharedState() { try? store.write(["ready": true], to: "container-ready.json") }
    pending = options.urlContexts.first?.url
    opener = options.urlContexts.first?.options.sourceApplication
  }
  func scene(_ scene: UIScene, openURLContexts contexts: Set<UIOpenURLContext>) {
    pending = contexts.first?.url; opener = contexts.first?.options.sourceApplication; returnToSource()
  }
  func sceneDidBecomeActive(_ scene: UIScene) { returnToSource() }
  @objc private func returnToSource() {
    guard UIApplication.shared.applicationState == .active, let url = pending else { return }
    pending = nil
    let token = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first { $0.name == "token" }?.value
    let store = SharedState(), request = token.flatMap { store?.consumeActivation($0) }
    var diagnostic = ClarifyReturnDiagnostics() as? [String: Any] ?? [:]
    diagnostic["nonceConsumed"] = request != nil
    diagnostic["source"] = request?.sourceBundleID ?? "unknown"
    diagnostic["systemSource"] = opener ?? "unknown"
    diagnostic["opened"] = request != nil && ClarifyReturnBridge.openSource(bundleID: request?.sourceBundleID)
    if let store { try? store.write(diagnostic.mapValues { String(describing: $0) }, to: "return-trace.json") }
  }
}
