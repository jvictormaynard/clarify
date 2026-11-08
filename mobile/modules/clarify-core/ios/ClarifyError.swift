import Foundation

struct ClarifyError: LocalizedError {
  let message: String
  // Diagnostics are optional, bounded values selected by the client. Never keep
  // provider response bodies, credentials or audio in an error.
  let code: String?
  let phase: String?
  let operationID: String?
  let status: Int?
  init(_ message: String, code: String? = nil, phase: String? = nil, operationID: String? = nil, status: Int? = nil) {
    self.message = message; self.code = code; self.phase = phase; self.operationID = operationID; self.status = status
  }
  var errorDescription: String? { L(message) }
}
