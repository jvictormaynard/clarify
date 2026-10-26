import { t } from "./i18n";
import { useLayoutEffect, useRef } from "react";
import { AlertCircle, LoaderCircle } from "lucide-react";
import { Titlebar } from "./components/titlebar";
import { Button } from "./components/ui";
import { SettingsNavigation } from "./components/settings-navigation";
import { GeneralPage } from "./pages/general-page";
import { AccountPage } from "./pages/account-page";
import { HistoryPage } from "./pages/history-page";
import { OnboardingPage } from "./pages/onboarding-page";
import { DictationPractice, PracticeEntry } from "./components/dictation-practice";
import { DictationPage } from "./pages/dictation-page";
import { TextPage } from "./pages/text-page";
import { SnippetsPage } from "./pages/snippets-page";
import { DictionaryPage } from "./pages/dictionary-page";
import { ShortcutsPage } from "./pages/shortcuts-page";
import { ModelsPage } from "./pages/models-page";
import { getSettingsPages } from "./settings/navigation";
import { SettingsDialogs } from "./settings/settings-dialogs";
import { useSettings } from "./settings/use-settings";

const pageComponents = {
  account: AccountPage,
  history: HistoryPage,
  general: GeneralPage,
  dictation: DictationPage,
  text: TextPage,
  dictionary: DictionaryPage,
  snippets: SnippetsPage,
  shortcuts: ShortcutsPage,
  models: ModelsPage,
};

export function App() {
  const controller = useSettings();
  const { state, page, error, pageDirty, saved, routeLoading, saving, discardingDrafts } = controller;
  const scrollArea = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (scrollArea.current) scrollArea.current.scrollTop = 0;
  }, [page]);
  const managed = !!(state?.accountState?.managed || state?.accountState?.signedIn);
  const settingsPages = getSettingsPages();
  const visiblePages = settingsPages.filter(item => !managed || (item.id !== "models" && item.id !== "text"));
  const activePage = managed && (page === "models" || page === "text") ? "account" : page;
  const waitingForRoute = routeLoading && (activePage === "dictation" || activePage === "text");
  const Page = pageComponents[activePage];
  const info = settingsPages.find((item) => item.id === activePage)!;

  return (
    <div className="settings-window">
      <Titlebar
        pageLabel={state?.onboardingRequired || state?.practiceState?.open ? undefined : info.label}
        onClose={() => controller.setClosing(true)}
        onError={controller.setError}
      />
      {state?.onboardingRequired ? <OnboardingPage controller={{ ...controller, state }} /> : state?.practiceState?.open ? <DictationPractice controller={{ ...controller, state }} /> : <div className="app">
        <aside>
          <SettingsNavigation pages={visiblePages} activePage={activePage}
            version={state?.applicationVersion} onNavigate={controller.navigate} />
        </aside>
        <main>
          <div className="scroll-area" ref={scrollArea}>
            <header className="page-header">
              <div className="page-heading"><span className="page-icon"><info.icon size={20} strokeWidth={1.5} /></span><h1>{info.label}</h1></div>
            </header>
            <div className="page">
              {error && (
                <div role="alert" className="error settings-error">
                  <AlertCircle size={17} />
                  <span>{t(error)}</span>
                </div>
              )}
              {!state ? (
                <div className="connection" role="status">
                  <LoaderCircle className="spin" size={22} />{t("Conectando ao Clarify…")}</div>
              ) : waitingForRoute ? (
                <div className="connection" role="status"><LoaderCircle className="spin" size={22} />{t("Carregando…")}</div>
              ) : (
                <div className="page-content">
                  {(activePage === "general" || activePage === "models") && <PracticeEntry controller={{ ...controller, state }} />}
                  <Page key={activePage === "snippets" || activePage === "dictionary"
                    ? `${activePage}:${state.snippetContext}` : activePage} controller={{ ...controller, state }} />
                </div>
              )}
              {pageDirty && !waitingForRoute && <div className="draft-actions" role="group" aria-label={t("Alterações pendentes")}>
                <span>{t("Alterações pendentes")}</span>
                <Button variant="ghost" disabled={saving || discardingDrafts}
                  onClick={() => controller.setDiscarding(true)}>{t("Descartar")}</Button>
                <Button variant="primary" aria-label={t("Salvar alterações")}
                  disabled={saving || discardingDrafts || !state}
                  onClick={() => void controller.save()}>
                  {saving && <LoaderCircle size={15} className="spin" />}{t("Salvar")}
                </Button>
              </div>}
            </div>
          </div>
          <span className="sr-only" role="status">
            {saved ? t("Alterações salvas") : ""}
          </span>
        </main>
        <SettingsDialogs controller={controller} />
      </div>}
    </div>
  );
}
