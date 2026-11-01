import UIKit
#if SWIFT_PACKAGE
import KeyboardHostSupport
#endif

struct HostActivationScope {
  let id = UUID()
  let document: UUID?
  let generation: UInt64

  func matches(_ current: Self?, document: UUID?) -> Bool {
    guard let document else { return false }
    return current?.id == id && self.document == document
  }
  func source(_ current: Self?, document: UUID?, read: (UInt64) -> String?) -> String? {
    guard matches(current, document: document) else { return nil }
    return read(generation)
  }
}

extension KeyboardViewController {
  private var activationDocument: UUID? {
    KBHostArbiterHook.documentIdentifier(for: textDocumentProxy)
  }
  func beginActivationSourceScope() {
    activationSourceScope = HostActivationScope(document: activationDocument,
      generation: KBHostArbiterHook.beginCaptureGeneration())
  }
  func refreshActivationDocument() {
    guard let scope = activationSourceScope,
          scope.document != activationDocument else { return }
    beginActivationSourceScope()
    if viewIfLoaded?.window != nil { KBHostArbiterHook.activeArbiterCheck() }
  }
  func activationURL() async -> URL? {
    guard !Task.isCancelled, isViewLoaded, view.window != nil else { return nil }
    refreshActivationDocument()
    guard let scope = activationSourceScope,
          scope.matches(activationSourceScope, document: activationDocument) else { return nil }
    var source: String?
    if #available(iOS 26.4, *) {
      KBHostArbiterHook.activeArbiterCheck()
      let clock = ContinuousClock(), deadline = clock.now.advanced(by: .milliseconds(400))
      // Yield the main actor so UIKit can deliver its destination callback.
      // A nested run loop inside the button action cannot drain a queued main
      // dispatch block while the current block is still executing.
      while view.window != nil, !Task.isCancelled {
        guard scope.matches(activationSourceScope, document: activationDocument) else { return nil }
        source = scope.source(activationSourceScope, document: activationDocument) {
          KBHostArbiterHook.hostBundleId(capturedAfter: $0)
        }
        if source != nil || clock.now >= deadline { break }
        do { try await Task.sleep(nanoseconds: 20_000_000) } catch { return nil }
      }
    }
    if source == nil {
      // Resolve the current controller's live host connection when the arbiter
      // has not delivered a fresh destination. Never use a historical capture.
      source = KBHostArbiterHook.legacyHostBundleID(for: self)
    }
    guard !Task.isCancelled, view.window != nil,
          scope.matches(activationSourceScope, document: activationDocument) else { return nil }
    // Unknown source is handled by the system navigation fallback in the app.
    let request = ActivationRequest(sourceBundleID: source)
    guard let store = store, (try? store.write(request, to: "activation.json")) != nil else {
      return URL(string: "clarify://keyboard")!
    }
    var url = URLComponents(string: "clarify://keyboard")!
    url.queryItems = [URLQueryItem(name: "token", value: request.token)]
    return url.url!
  }
  func invalidateActivationSource() {
    activationSourceScope = nil
    KBHostArbiterHook.invalidateCache()
  }
}
