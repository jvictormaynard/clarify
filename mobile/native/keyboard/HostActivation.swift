import UIKit
#if SWIFT_PACKAGE
import KeyboardHostSupport
#endif

extension KeyboardViewController {
  func activationURL() async -> URL? {
    guard !Task.isCancelled, isViewLoaded, view.window != nil else { return nil }
    var source: String?
    if #available(iOS 26.4, *) {
      // A connected arbiter need not emit another callback. Its current state
      // is usable only when its process matches this controller's current host.
      source = KBHostArbiterHook.currentHostBundleID(for: self)
      if source == nil {
        let generation = KBHostArbiterHook.captureGeneration()
        KBHostArbiterHook.activeArbiterCheck()
        let clock = ContinuousClock(), deadline = clock.now.advanced(by: .milliseconds(400))
        // Yield the main actor so UIKit can deliver its destination callback.
        // A nested run loop inside the button action cannot drain a queued main
        // dispatch block while the current block is still executing.
        while view.window != nil, !Task.isCancelled {
          source = KBHostArbiterHook.hostBundleId(capturedAfter: generation)
          if source != nil || clock.now >= deadline { break }
          do { try await Task.sleep(nanoseconds: 20_000_000) } catch { return nil }
        }
      }
    } else {
      source = KBHostArbiterHook.legacyHostBundleID(for: self)
    }
    guard !Task.isCancelled, view.window != nil else { return nil }
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
