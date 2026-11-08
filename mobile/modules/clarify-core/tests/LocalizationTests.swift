import XCTest
@testable import ClarifyContracts

final class LocalizationTests: XCTestCase {
  func testRegionalLocalesAndUnsupportedLanguageFallback() {
    XCTAssertEqual(ClarifyLocale.normalize("pt-BR"), "pt")
    XCTAssertEqual(ClarifyLocale.normalize("es_MX"), "es")
    XCTAssertEqual(ClarifyLocale.normalize("en-GB"), "en")
    XCTAssertEqual(ClarifyLocale.normalize("de-DE"), "en")
  }
  func testSharedAuthenticationLabelsAndSubstitutions() {
    XCTAssertEqual(L("Continuar sem conta", language: "pt"), "Continuar sem conta")
    XCTAssertEqual(L("Continuar sem conta", language: "en"), "Continue without an account")
    XCTAssertEqual(L("Continuar sem conta", language: "es"), "Continuar sin cuenta")
    XCTAssertEqual(L("email_subject", language: "en-US"), "Your access code")
    XCTAssertEqual(L("email_subject", language: "es-MX"), "Tu código de acceso")
    XCTAssertEqual(L("Usar {word}", ["word": "Clarify"], language: "en"), "Use Clarify")
  }
}
