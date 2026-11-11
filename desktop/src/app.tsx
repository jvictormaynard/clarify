import { t } from "./i18n";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import logo from "../src-tauri/icons/clarify.png";
import { AlertCircle, LoaderCircle, UserRound, PanelLeft } from "lucide-react";
import { Titlebar } from "./components/titlebar";
import { Button } from "./components/ui";
import { SettingsNavigation } from "./components/settings-navigation";
import { SettingsDialog } from "./components/settings-dialog";
import { TextActionEditor } from "./components/text-action-editor";
import { TextProfileEditor } from "./components/text-profile-editor";
import { HomePage } from "./pages/home-page";
import { OnboardingPage } from "./pages/onboarding-page";
import { DictationPractice } from "./components/dictation-practice";

import { StylePage } from "./pages/style-page";
import { ActionsPage } from "./pages/actions-page";
import { SnippetsPage } from "./pages/snippets-page";
import { DictionaryPage } from "./pages/dictionary-page";
import { getMainPages, isWorkflowPage } from "./settings/navigation";
import { SettingsDialogs } from "./settings/settings-dialogs";
import { useSettings } from "./settings/use-settings";

const pageComponents = {
  history: HomePage,
  style: StylePage,
  actions: ActionsPage,
  dictionary: DictionaryPage,
  snippets: SnippetsPage,
};

export function App() {
  const controller = useSettings();
  const [collapsed, setCollapsed] = useState(false);
  const [compact, setCompact] = useState(() => window.matchMedia("(max-width: 767px)").matches);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 767px)");
    const change = () => setCompact(media.matches);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  const { state, mainPage, settingsOpen, error, saved, routeLoading, saving, discardingDrafts } = controller;
  const scrollArea = useRef<HTMLDivElement>(null);
  const settingsButton = useRef<HTMLButtonElement>(null);
  const settingsOpener = useRef<HTMLButtonElement>(null);
  const background = useRef(controller);
  const waitingForRoute = !settingsOpen && routeLoading && isWorkflowPage(mainPage);
  const retainPage = background.current.mainPage === mainPage && !!background.current.state;
  if (!settingsOpen && !waitingForRoute) background.current = controller;
  const pageController = settingsOpen || (waitingForRoute && retainPage) ? background.current : controller;
  const pageState = pageController.state;
  useLayoutEffect(() => {
    if (scrollArea.current) scrollArea.current.scrollTop = 0;
  }, [mainPage]);
  const pages = getMainPages();
  const Page = pageComponents[mainPage];
  const info = pages.find(item => item.id === mainPage)!;

  return (
    <div className="settings-window" data-sidebar-collapsed={collapsed || compact} onClickCapture={event => {
      if (!settingsOpen && event.target instanceof Element) settingsOpener.current = event.target.closest("button");
    }}>
      <Titlebar
        showBrand={false}
        navigation={state && !state.onboardingRequired && !state.practiceState?.open ? <Button variant="ghost" disabled={compact} aria-label={t("Barra lateral")} title={t("Barra lateral")} aria-expanded={!collapsed && !compact} aria-controls="desktop-sidebar" onClick={() => setCollapsed(value => !value)}><PanelLeft size={18} /></Button> : undefined}
        pageLabel={undefined}
        actions={state && !state.onboardingRequired && !state.practiceState?.open ? <Button variant="ghost" aria-label={t("Conta")} title={t("Conta")} onClick={() => void controller.navigate("account")}><UserRound size={18} /></Button> : undefined}
        onClose={() => controller.setClosing(true)}
        onError={controller.setError}
      />
      {state?.onboardingRequired ? <OnboardingPage controller={{ ...controller, state }} /> : state?.practiceState?.open ? <DictationPractice controller={{ ...controller, state }} /> : <div className="app">
        <aside id="desktop-sidebar">
          <div className="sidebar-brand"><img src={logo} alt="" /><span>Clarify</span></div>
          <SettingsNavigation pages={pages} activePage={mainPage} settingsButtonRef={settingsButton}
            onNavigate={controller.navigate}
            onOpenSettings={() => void controller.navigate(controller.settingsSection)} />
        </aside>
        <main>
          <div className="scroll-area" ref={scrollArea}>
            <div className="page">
              {mainPage !== "snippets" && mainPage !== "dictionary" && mainPage !== "actions" && <header className="workspace-page-header"><info.icon size={24} aria-hidden /><h1>{mainPage === "history" ? t("Bem-vindo de volta") : info.label}</h1></header>}
              {error && (
                <div role="alert" className="error settings-error">
                  <AlertCircle size={17} />
                  <span>{t(error)}</span>
                </div>
              )}
              {!pageState ? (
                <div className="connection" role="status">
                  <LoaderCircle className="spin" size={22} />{t("Conectando ao Clarify…")}</div>
              ) : waitingForRoute && !retainPage ? (
                <div className="connection" role="status"><LoaderCircle className="spin" size={22} />{t("Carregando…")}</div>
              ) : (
                <div className="page-content" inert={waitingForRoute} aria-busy={waitingForRoute}>
                  <Page key={mainPage === "snippets" || mainPage === "dictionary"
                    ? `${mainPage}:${pageState.snippetContext}` : mainPage} controller={{ ...pageController, state: pageState }} />
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
        <SettingsDialog controller={{ ...controller, settingsOpen: settingsOpen && !state.practiceState?.open && !state.onboardingRequired, state }} returnFocus={settingsOpener.current?.isConnected ? settingsOpener : settingsButton} />
        <TextActionEditor controller={{ ...controller, state }} />
        <TextProfileEditor controller={{ ...controller, state }} />
      </>}
      <SettingsDialogs controller={controller} />
    </div>
  );
}
