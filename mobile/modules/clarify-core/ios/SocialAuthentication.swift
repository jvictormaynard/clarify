import Foundation
import CryptoKit
import Security

// Only the containing app creates and holds these values. No defaults, App
// Group, browser URL, Router route or JavaScript snapshot receives the verifier.
enum SocialPKCE {
  static func verifier() throws -> String {
    var bytes = [UInt8](repeating: 0, count: 32)
    let status = bytes.withUnsafeMutableBytes { SecRandomCopyBytes(kSecRandomDefault, $0.count, $0.baseAddress!) }
    guard status == errSecSuccess else { throw ClarifyError(L("Não foi possível iniciar a entrada com este provedor. Tente novamente.")) }
    return encode(Data(bytes))
  }
  static func challenge(_ verifier: String) -> String { encode(Data(SHA256.hash(data: Data(verifier.utf8)))) }
  private static func encode(_ data: Data) -> String {
    data.base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
  }
}

struct SocialBrowser {
  var open: @MainActor (URL) async throws -> URL
  var cancel: @MainActor () -> Void
  static var system: SocialBrowser {
    SocialBrowser(open: { url in
      #if canImport(AuthenticationServices) && canImport(UIKit)
      return try await SystemSocialBrowser.shared.open(url)
      #else
      throw ClarifyError(L("Não foi possível abrir a página de entrada. Tente novamente."))
      #endif
    }, cancel: {
      #if canImport(AuthenticationServices) && canImport(UIKit)
      SystemSocialBrowser.shared.cancel()
      #endif
    })
  }
}

#if canImport(AuthenticationServices) && canImport(UIKit)
import AuthenticationServices
import UIKit

@MainActor private final class SystemSocialBrowser: NSObject, ASWebAuthenticationPresentationContextProviding {
  static let shared = SystemSocialBrowser()
  private var session: ASWebAuthenticationSession?
  private var continuation: CheckedContinuation<URL, Error>?
  private var operation: UUID?
  private var anchor: UIWindow?

  func open(_ url: URL) async throws -> URL {
    guard session == nil, UIApplication.shared.applicationState == .active,
      let window = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene })
        .filter({ $0.activationState == .foregroundActive }).flatMap(\.windows).first(where: \.isKeyWindow) else {
      throw ClarifyError(L("Não foi possível abrir a página de entrada. Tente novamente."))
    }
    let id = UUID()
    return try await withTaskCancellationHandler(operation: {
      try Task.checkCancellation()
      return try await withCheckedThrowingContinuation { continuation in
        self.operation = id; self.anchor = window; self.continuation = continuation
        let browser = ASWebAuthenticationSession(url: url, callbackURLScheme: "clarify") { [weak self] callback, error in
          Task { @MainActor in
            guard let self, self.operation == id else { return }
            if let error = error as? ASWebAuthenticationSessionError, error.code == .canceledLogin {
              self.finish(.failure(CancellationError()))
            } else if error != nil || callback == nil {
              self.finish(.failure(ClarifyError(L("Não foi possível concluir a entrada com este provedor. Tente novamente."))))
            } else if let callback { self.finish(.success(callback)) }
          }
        }
        browser.presentationContextProvider = self
        browser.prefersEphemeralWebBrowserSession = true
        self.session = browser
        if !browser.start() { self.finish(.failure(ClarifyError(L("Não foi possível abrir a página de entrada. Tente novamente.")))) }
      }
    }, onCancel: { Task { @MainActor in if self.operation == id { self.cancel() } } })
  }
  func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor { anchor ?? UIWindow() }
  func cancel() {
    session?.cancel()
    finish(.failure(CancellationError()))
  }
  private func finish(_ result: Result<URL, Error>) {
    let pending = continuation
    continuation = nil; operation = nil; session = nil; anchor = nil
    pending?.resume(with: result)
  }
}
#endif
