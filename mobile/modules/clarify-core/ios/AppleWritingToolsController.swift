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
  private let privateStyle: String?
  private var attemptedPrivateController = false
  private let editor = UITextView()
  private let translationHint = UILabel()

  init(source: String, target: String, privateStyle: String? = nil) {
    self.source = source; self.target = target; self.privateStyle = privateStyle
    super.init(nibName: nil, bundle: nil)
  }
  required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

  override func viewDidAppear(_ animated: Bool) {
    super.viewDidAppear(animated)
    guard let style = privateStyle, !attemptedPrivateController else { return }
    attemptedPrivateController = true
    editor.becomeFirstResponder()
    editor.selectedRange = NSRange(location: 0, length: (editor.text as NSString).length)
    var details: NSString?
    let invoked = ClarifyPrivateWritingToolsBridge.openTool(textView: editor, style: style, diagnostics: &details)
    // Invocation is not proof that a model generated or that an edit was accepted.
    let state = L(invoked ? "Controlador privado chamado. Confira se a Apple iniciou a reescrita." :
      "O controlador privado não pôde ser iniciado. O original foi preservado.")
    translationHint.text = state + "\n" + ((details as String?) ?? "")
  }

  override func viewDidDisappear(_ animated: Bool) {
    super.viewDidDisappear(animated)
    if isBeingDismissed || navigationController?.isBeingDismissed == true {
      ClarifyPrivateWritingToolsBridge.endTool(textView: editor)
    }
  }

  override func viewDidLoad() {
    super.viewDidLoad()
    title = L("Ferramentas de Escrita da Apple")
    view.backgroundColor = .systemBackground
    navigationItem.rightBarButtonItem = UIBarButtonItem(title: L("Concluir"), style: .done,
      target: self, action: #selector(close))
    let notice = UILabel()
    notice.text = L("As Ferramentas de Escrita usam os controles da Apple e podem usar o Private Cloud Compute. O botão Traduzir usa o idioma de saída do Clarify e processa a tradução neste iPhone.")
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
    let translate = UIButton(type: .system)
    let targetName = Locale(identifier: ClarifyLocale.language).localizedString(forLanguageCode: target) ?? target
    translate.setTitle(target == "auto" ? L("Selecione um idioma de saída na tela anterior.") :
      L("Traduzir para {language}", ["language": targetName]), for: .normal)
    translate.accessibilityIdentifier = "apple.native.translate"
    translate.isEnabled = target != "auto"
    translate.addTarget(self, action: #selector(translateCurrentText), for: .touchUpInside)
    translationHint.numberOfLines = 0
    translationHint.font = .preferredFont(forTextStyle: .footnote)
    translationHint.text = L("Aceite a reescrita com ✓. Depois, toque em Traduzir. A tradução usa o texto deste editor e é processada neste iPhone.")
    for button in [tools, languages, translate] {
      button.titleLabel?.numberOfLines = 0
      button.titleLabel?.textAlignment = .center
      button.heightAnchor.constraint(greaterThanOrEqualToConstant: 44).isActive = true
    }
    let stack = UIStackView(arrangedSubviews: [notice, tools, languages, translate, translationHint, editor])
    stack.axis = .vertical; stack.spacing = 12; stack.translatesAutoresizingMaskIntoConstraints = false
    let scroll = UIScrollView()
    scroll.alwaysBounceVertical = true; scroll.keyboardDismissMode = .interactive
    scroll.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(scroll); scroll.addSubview(stack)
    NSLayoutConstraint.activate([
      scroll.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
      scroll.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor),
      scroll.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor),
      scroll.bottomAnchor.constraint(equalTo: view.keyboardLayoutGuide.topAnchor),
      stack.topAnchor.constraint(equalTo: scroll.contentLayoutGuide.topAnchor, constant: 16),
      stack.leadingAnchor.constraint(equalTo: scroll.contentLayoutGuide.leadingAnchor, constant: 20),
      stack.trailingAnchor.constraint(equalTo: scroll.contentLayoutGuide.trailingAnchor, constant: -20),
      stack.bottomAnchor.constraint(equalTo: scroll.contentLayoutGuide.bottomAnchor, constant: -12),
      stack.widthAnchor.constraint(equalTo: scroll.frameLayoutGuide.widthAnchor, constant: -40),
      editor.heightAnchor.constraint(greaterThanOrEqualToConstant: 240)
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
    openTranslation(translateText: false)
  }
  @objc private func translateCurrentText() {
    openTranslation(translateText: true)
  }
  private func openTranslation(translateText: Bool) {
    #if canImport(Translation)
    if #available(iOS 26.0, *), target != "auto" {
      guard presentedViewController == nil else { return }
      guard !editor.isWritingToolsActive else {
        translationHint.text = L("Aceite ou cancele a alteração nas Ferramentas de Escrita antes de traduzir.")
        return
      }
      let currentText = editor.text ?? ""
      guard !currentText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
        currentText.utf8.count <= AppleRewriteEngine.maxOutputBytes else {
        translationHint.text = L("Use um texto não vazio de até 8.000 bytes para traduzir.")
        return
      }
      editor.resignFirstResponder()
      // Freeze the accepted editor contents, including Writing Tools changes.
      // The result is read-only in another sheet; never replace the source.
      let content = AppleTranslationPreparation(source: currentText, target: target, translateText: translateText)
      present(UIHostingController(rootView: content), animated: true)
    }
    #endif
  }
  @objc private func close() {
    ClarifyPrivateWritingToolsBridge.endTool(textView: editor)
    dismiss(animated: true)
  }
}

#if canImport(Translation)
@available(iOS 26.0, *)
private struct AppleTranslationPreparation: View {
  let source: String
  let target: String
  let translateText: Bool
  @Environment(\.dismiss) private var dismiss
  @State private var configuration: TranslationSession.Configuration?
  @State private var status = ""
  @State private var busy = false
  @State private var result = ""
  var body: some View {
    NavigationStack {
      ScrollView {
        VStack(alignment: .leading, spacing: 20) {
          Text(L(translateText ? "A tradução usa o texto atual do editor. O texto do editor permanece disponível ao fechar esta tela." :
            "A Apple pode solicitar o download dos idiomas. Depois, volte ao teste de reescrita."))
          Button(L(translateText ? "Traduzir" : "Preparar idiomas")) { start() }.disabled(busy)
          if busy { ProgressView() }
          if !status.isEmpty { Text(status).accessibilityIdentifier("apple.native.translation.status") }
          if !result.isEmpty {
            Text(L("Resultado")).font(.headline)
            Text(result).textSelection(.enabled).accessibilityIdentifier("apple.native.translation.result")
          }
        }.padding()
      }
        .navigationTitle(L("Tradução local"))
        .toolbar { Button(L("Concluir")) { dismiss() } }
        .onAppear { if translateText && configuration == nil { start() } }
        .translationTask(configuration) { session in
          do {
            try await session.prepareTranslation()
            try Task.checkCancellation()
            if translateText {
              let response = try await session.translate(source)
              try Task.checkCancellation()
              let translated = response.targetText.trimmingCharacters(in: .whitespacesAndNewlines)
              guard !translated.isEmpty, translated.utf8.count <= AppleRewriteEngine.maxOutputBytes else {
                status = L("Translation did not return complete text. The source was preserved.")
                busy = false; return
              }
              result = translated
            } else { status = L("Idiomas prontos. Volte ao teste de reescrita.") }
          } catch is CancellationError { }
          catch { status = L(translateText ? "A tradução falhou. O texto do editor foi preservado. Tente novamente." :
            "Não foi possível preparar os idiomas. Tente novamente.") }
          busy = false
        }
    }
  }
  private func start() {
    busy = true; status = ""; result = ""
    guard let language = NLLanguageRecognizer.dominantLanguage(for: source) else {
      busy = false; status = L("The source language could not be identified. Use a longer sample."); return
    }
    guard language.rawValue != target else {
      busy = false; status = L("O texto já está no idioma selecionado."); return
    }
    if configuration != nil { configuration?.invalidate() }
    else {
      configuration = TranslationSession.Configuration(source: Locale.Language(identifier: language.rawValue),
        target: Locale.Language(identifier: target))
    }
  }
}
#endif
