import UIKit

// One keyboard-owned edit, kept only in memory. The document stays owned by the
// host. Context and identity checks prevent an old button from deleting new text.
@MainActor
struct DictationEdit {
  private struct Context: Equatable {
    let document: UUID
    let before: String
    let after: String
    let hasText: Bool
    init?(_ proxy: UITextDocumentProxy) {
      guard proxy.isSecureTextEntry != true, proxy.selectedText?.isEmpty != false else { return nil }
      let before = proxy.documentContextBeforeInput ?? "", after = proxy.documentContextAfterInput ?? ""
      guard !before.isEmpty || !after.isEmpty || !proxy.hasText else { return nil }
      self.document = proxy.documentIdentifier
      self.before = before; self.after = after; self.hasText = proxy.hasText
    }
  }
  private let text: String
  private let replaced: String
  private var context: Context
  private(set) var removed = false

  init?(text: String, replaced: String, proxy: UITextDocumentProxy) {
    guard !text.isEmpty, let context = Context(proxy), !context.before.isEmpty,
          context.before.hasSuffix(String(text.suffix(context.before.count))) else { return nil }
    self.text = text; self.replaced = replaced; self.context = context
  }
  func isCurrent(_ proxy: UITextDocumentProxy) -> Bool { Context(proxy) == context }
  mutating func toggle(in proxy: UITextDocumentProxy) -> Bool {
    guard isCurrent(proxy) else { return false }
    let deleted = removed ? replaced : text, inserted = removed ? text : replaced
    for _ in deleted { proxy.deleteBackward() }
    if !inserted.isEmpty { proxy.insertText(inserted) }
    guard let next = Context(proxy) else { return false }
    context = next; removed.toggle()
    return true
  }
}
