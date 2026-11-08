import UIKit
import SwiftUI
import NaturalLanguage
#if canImport(Translation)
import Translation
#endif

// A separate, transient editor. System edits never enter dictation or history.
@MainActor
final class AppleWritingToolsController: UIViewController {
  private let source: String
  private let target: String
  private let editor = UITextView()

  init(source: String, target: String) {
    self.source = source; self.target = target
    super.init(nibName: nil, bundle: nil)
  }
  required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

  override func viewDidLoad() {
    super.viewDidLoad()
    title = L("Ferramentas de Escrita da Apple")
    view.backgroundColor = .systemBackground
    navigationItem.rightBarButtonItem = UIBarButtonItem(title: L("Concluir"), style: .done,
      target: self, action: #selector(close))
    let notice = UILabel()
    notice.text = L("Esta comparação usa os controles da Apple e pode usar o Private Cloud Compute. As opções de idioma e estilo do Clarify não são aplicadas aqui.")
    notice.numberOfLines = 0; notice.font = .preferredFont(forTextStyle: .footnote)
    editor.text = source; editor.font = .preferredFont(forTextStyle: .body)
    editor.adjustsFontForContentSizeCategory = true
    editor.accessibilityLabel = L("Texto para processar")
    if #available(iOS 18.0, *) { editor.writingToolsBehavior = .complete }
    let tools = UIButton(type: .system)
    tools.setTitle(L("Abrir Ferramentas de Escrita"), for: .normal)
    tools.addTarget(self, action: #selector(openTools), for: .touchUpInside)
    let languages = UIButton(type: .system)
    languages.setTitle(L("Preparar idiomas para tradução local"), for: .normal)
    languages.addTarget(self, action: #selector(prepareLanguages), for: .touchUpInside)
    languages.isHidden = target == "auto"
    let stack = UIStackView(arrangedSubviews: [notice, tools, languages, editor])
    stack.axis = .vertical; stack.spacing = 12; stack.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(stack)
    NSLayoutConstraint.activate([
      stack.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 16),
      stack.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 20),
      stack.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -20),
      stack.bottomAnchor.constraint(equalTo: view.keyboardLayoutGuide.topAnchor, constant: -12)
    ])
  }

  @objc private func openTools() {
    if #available(iOS 18.2, *) {
      guard UIWritingToolsCoordinator.isWritingToolsAvailable else { return }
      editor.becomeFirstResponder()
      editor.selectedRange = NSRange(location: 0, length: (editor.text as NSString).length)
      editor.showWritingTools(self)
    }
  }
  @objc private func prepareLanguages() {
    #if canImport(Translation)
    if #available(iOS 26.0, *), target != "auto" {
      editor.resignFirstResponder()
      let content = AppleTranslationPreparation(source: source, target: target)
      present(UIHostingController(rootView: content), animated: true)
    }
    #endif
  }
  @objc private func close() { dismiss(animated: true) }
}

#if canImport(Translation)
@available(iOS 26.0, *)
private struct AppleTranslationPreparation: View {
  let source: String
  let target: String
  @Environment(\.dismiss) private var dismiss
  @State private var configuration: TranslationSession.Configuration?
  @State private var status = ""
  @State private var busy = false
  var body: some View {
    NavigationStack {
      VStack(spacing: 20) {
        Text(L("A Apple pode solicitar o download dos idiomas. Depois, volte ao teste de reescrita."))
        Button(L("Preparar idiomas")) {
          busy = true; status = ""
          guard let language = NLLanguageRecognizer.dominantLanguage(for: source) else {
            busy = false; status = L("The source language could not be identified. Use a longer sample."); return
          }
          if configuration != nil { configuration?.invalidate() }
          else {
            configuration = TranslationSession.Configuration(source: Locale.Language(identifier: language.rawValue),
              target: Locale.Language(identifier: target))
          }
        }.disabled(busy)
        Text(status)
      }.padding()
        .navigationTitle(L("Tradução local"))
        .toolbar { Button(L("Concluir")) { dismiss() } }
        .translationTask(configuration) { session in
          do {
            try await session.prepareTranslation()
            status = L("Idiomas prontos. Volte ao teste de reescrita.")
          } catch is CancellationError { }
          catch { status = L("Não foi possível preparar os idiomas. Tente novamente.") }
          busy = false
        }
    }
  }
}
#endif
