import { stopRecordingPlayback } from "./settings/recording-playback";
import { t } from "./i18n";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import logo from "../assets/clarify.png";
import { AlertCircle, LoaderCircle, UserRound, PanelLeft } from "lucide-react";
import { Titlebar } from "./components/titlebar";
import { Button } from "./components/ui";
import { SettingsNavigation } from "./components/settings-navigation";
import { SettingsDialog } from "./components/settings-dialog";
import { TextActionEditor } from "./components/text-action-editor";
import { TextProfileEditor } from "./components/text-profile-editor";
import { HomePage } from "./pages/home-page";
import { MeetingsPage } from "./pages/meetings-page";
import { meetingError } from "./pages/meetings-copy";
import { meetingStopFromDock } from "./meetings/bridge";
import { MeetingQuitDialog } from "./meetings/window";
import { electron } from "./platform";
import { OnboardingPage, type SetupPurpose } from "./pages/onboarding-page";
import { DictationPractice } from "./components/dictation-practice";

import { StylePage } from "./pages/style-page";
import { ActionsPage } from "./pages/actions-page";
import { SnippetsPage } from "./pages/snippets-page";
import { DictionaryPage } from "./pages/dictionary-page";
import { getMainPages } from "./settings/navigation";
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
  const [meetingOpen, setMeetingOpen] = useState<{ target?: string } | null>(null);
  const acknowledgeMeetingOpen = useCallback((request: { target?: string }) => {
    setMeetingOpen(current => current === request ? null : current);
  }, []);
  const currentController = useRef(controller);
  currentController.current = controller;
  useEffect(() => electron()?.onWindow((event, target) => {
    if (event === "meetings") {
      setMeetingOpen({ target });
    }
    if (event === "meeting-stop" && target) {
      void meetingStopFromDock(target).catch(error => {
        setMeetingOpen({ target });
        currentController.current.setError(meetingError(error instanceof Error ? error.message : ""));
      });
    }
    if (event === "meeting-models") void currentController.current.navigate("models");
  }), []);
  const canOpenMeeting = !!controller.state && !controller.state.onboardingRequired && !controller.state.practiceState?.open;
  useEffect(() => {
    if (meetingOpen && canOpenMeeting) void currentController.current.navigate("meetings");
  }, [meetingOpen, canOpenMeeting]);
  const setupWasRequired = useRef(false);
  const setupPurpose = useRef<SetupPurpose>("dictation");
  const setupCloudSpeech = useRef(false);
  useEffect(() => {
    if (!controller.state) return;
    const completed = setupWasRequired.current && !controller.state.onboardingRequired;
    setupWasRequired.current = controller.state.onboardingRequired;
    if (completed) {
      if (setupPurpose.current !== "dictation") void currentController.current.navigate("meetings");
      if (setupCloudSpeech.current) {
        void currentController.current.navigate("models");
        return;
      }
      if (setupPurpose.current !== "meetings") void controller.run("practiceCommand", "open");
    }
  }, [controller.state?.onboardingRequired, controller.run]);
  const [collapsed, setCollapsed] = useState(false);
  const [compact, setCompact] = useState(() => window.matchMedia("(max-width: 767px)").matches);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 767px)");
    const change = () => setCompact(media.matches);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  const { state, mainPage, settingsOpen, error, saved, saving, discardingDrafts } = controller;
  useEffect(() => {
    if (state?.audioPlaybackStopRequest) void stopRecordingPlayback(state.audioPlaybackStopRequest).catch(() => {});
  }, [state?.audioPlaybackStopRequest]);
  const scrollArea = useRef<HTMLDivElement>(null);
  const settingsButton = useRef<HTMLButtonElement>(null);
  const settingsOpener = useRef<HTMLButtonElement>(null);
  const background = useRef(controller);
  if (!settingsOpen) background.current = controller;
  const pageController = settingsOpen ? background.current : controller;
  const pageState = pageController.state;
  useLayoutEffect(() => {
    if (scrollArea.current) scrollArea.current.scrollTop = 0;
  }, [mainPage]);
  const pages = getMainPages();
  const Page = mainPage === "meetings" ? MeetingsPage : pageComponents[mainPage];
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
      {state?.onboardingRequired ? <OnboardingPage controller={{ ...controller, state }} onChoosePurpose={purpose => { setupPurpose.current = purpose; setupCloudSpeech.current = false; }} onCloudSpeechSetup={() => { setupCloudSpeech.current = true; }} /> : state?.practiceState?.open ? <DictationPractice controller={{ ...controller, state }} /> : <div className="app">
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
              ) : (
                <div className="page-content">
                  <Page key={mainPage === "snippets" || mainPage === "dictionary"
                    ? `${mainPage}:${pageState.snippetContext}` : mainPage} controller={{ ...pageController, state: pageState }}
                    meetingOpen={meetingOpen} acknowledgeMeetingOpen={acknowledgeMeetingOpen} />
                </div>
              )}
              {pageController.pageDirty && <div className="draft-actions" role="group" aria-label={t("Alterações pendentes")}>
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
        <SettingsDialog controller={{ ...controller, settingsOpen: settingsOpen && !state.practiceState?.open && !state.onboardingRequired, state }} returnFocus={() => settingsOpener.current?.isConnected ? settingsOpener.current : settingsButton.current} />
        <TextActionEditor controller={{ ...controller, state }} />
        <TextProfileEditor controller={{ ...controller, state }} />
      </>}
      <SettingsDialogs controller={controller} />
      <MeetingQuitDialog />
    </div>
  );
}
