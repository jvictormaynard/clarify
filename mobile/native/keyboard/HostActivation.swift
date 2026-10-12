import UIKit
#if SWIFT_PACKAGE
import KeyboardHostSupport
#endif

extension KeyboardViewController {
  func activationURL() -> URL {
    var source: String?
    if isViewLoaded, view.window != nil {
      if #available(iOS 26.4, *) {
        let generation = KBHostArbiterHook.captureGeneration()
        KBHostArbiterHook.activeArbiterCheck()
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.05))
        if view.window != nil { source = KBHostArbiterHook.hostBundleId(capturedAfter: generation) }
      } else {
        source = KBHostArbiterHook.legacyHostBundleID(for: self)
      }
    }
    // Unknown source is handled by the system navigation fallback in the app.
    let request = ActivationRequest(sourceBundleID: source)
    guard let store = store, (try? store.write(request, to: "activation.json")) != nil else {
      return URL(string: "clarify://keyboard")!
    }
    var url = URLComponents(string: "clarify://keyboard")!
    url.queryItems = [URLQueryItem(name: "token", value: request.token)]
    return url.url!
  }
  func invalidateActivationSource() { KBHostArbiterHook.invalidateCache() }
}
