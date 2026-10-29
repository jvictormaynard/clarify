import { t } from "./i18n";
import { useLayoutEffect, useRef } from "react";
import { AlertCircle, LoaderCircle } from "lucide-react";
import { Titlebar } from "./components/titlebar";
import { Button } from "./components/ui";
import { SettingsNavigation } from "./components/settings-navigation";
import { SettingsDialog } from "./components/settings-dialog";
import { TextActionEditor } from "./components/text-action-editor";
import { AppStyleEditor } from "./components/app-style-editor";
import { TextProfileEditor } from "./components/text-profile-editor";
import { HistoryPage } from "./pages/history-page";
import { OnboardingPage } from "./pages/onboarding-page";
import { DictationPractice, PracticeEntry } from "./components/dictation-practice";
import { DictationPage } from "./pages/dictation-page";
import { StylePage } from "./pages/style-page";
import { ActionsPage } from "./pages/actions-page";
import { SnippetsPage } from "./pages/snippets-page";
import { DictionaryPage } from "./pages/dictionary-page";
import { getMainPages, isWorkflowPage } from "./settings/navigation";
import { SettingsDialogs } from "./settings/settings-dialogs";
import { useSettings } from "./settings/use-settings";

const pageComponents = {
  history: HistoryPage,
  dictation: DictationPage,
  style: StylePage,
  actions: ActionsPage,
  dictionary: DictionaryPage,
  snippets: SnippetsPage,
};

export function App() {
  const controller = useSettings();
  const { state, mainPage, settingsOpen, error, saved, routeLoading, saving, discardingDrafts } = controller;
  const scrollArea = useRef<HTMLDivElement>(null);
  const settingsButton = useRef<HTMLButtonElement>(null);
  const background = useRef(controller);
  if (!settingsOpen) background.current = controller;
  const pageController = settingsOpen ? background.current : controller;
  const pageState = pageController.state;
  useLayoutEffect(() => {
    if (scrollArea.current) scrollArea.current.scrollTop = 0;
  }, [mainPage]);
  const pages = getMainPages();
  const waitingForRoute = !settingsOpen && routeLoading && isWorkflowPage(mainPage);
  const Page = pageComponents[mainPage];
  const info = pages.find(item => item.id === mainPage)!;

  return (
    <div className="settings-window">
      <Titlebar
        pageLabel={state?.onboardingRequired || state?.practiceState?.open ? undefined : info.label}
        onClose={() => controller.setClosing(true)}
        onError={controller.setError}
      />
      {state?.onboardingRequired ? <OnboardingPage controller={{ ...controller, state }} /> : state?.practiceState?.open ? <DictationPractice controller={{ ...controller, state }} /> : <div className="app">
        <aside>
          <SettingsNavigation pages={pages} activePage={mainPage} settingsButtonRef={settingsButton}
            version={state?.applicationVersion} onNavigate={controller.navigate}
            onOpenSettings={() => void controller.navigate(controller.settingsSection)} />
        </aside>
        <main>
          <div className="scroll-area" ref={scrollArea}>
            <h1 className="sr-only">{info.label}</h1>
            <div className="page">
              {error && (
                <div role="alert" className="error settings-error">
                  <AlertCircle size={17} />
                  <span>{t(error)}</span>
                </div>
              )}
              {!pageState ? (
                <div className="connection" role="status">
                  <LoaderCircle className="spin" size={22} />{t("Conectando ao Clarify…")}</div>
              ) : waitingForRoute ? (
                <div className="connection" role="status"><LoaderCircle className="spin" size={22} />{t("Carregando…")}</div>
              ) : (
                <div className="page-content">
                  <Page key={mainPage === "snippets" || mainPage === "dictionary"
                    ? `${mainPage}:${pageState.snippetContext}` : mainPage} controller={{ ...pageController, state: pageState }} />
                  {mainPage === "dictation" && <PracticeEntry controller={{ ...pageController, state: pageState }} />}
                </div>
              )}
              {pageController.pageDirty && !waitingForRoute && <div className="draft-actions" role="group" aria-label={t("Alterações pendentes")}>
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
      </div>}
      {state && <>
        <SettingsDialog controller={{ ...controller, settingsOpen: settingsOpen && !state.practiceState?.open && !state.onboardingRequired, state }} returnFocus={settingsButton} />
        <TextActionEditor controller={{ ...controller, state }} />
        <AppStyleEditor controller={{ ...controller, state }} />
        <TextProfileEditor controller={{ ...controller, state }} />
      </>}
      <SettingsDialogs controller={controller} />
    </div>
  );
}
