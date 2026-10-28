import { t } from "./i18n";
import { useCallback, useLayoutEffect, useRef, useState } from "react";
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
import type { SettingsSearchResult } from "./settings/search";

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
  const searchGeneration = useRef(0);
  const [searchTarget, setSearchTarget] = useState<(SettingsSearchResult & { generation: number }) | null>(null);
  const cancelSearchNavigation = useCallback(() => {
    searchGeneration.current += 1;
    setSearchTarget(null);
  }, []);
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
  useLayoutEffect(() => {
    if (!searchTarget || searchTarget.generation !== searchGeneration.current || activePage !== searchTarget.page.id || !state || waitingForRoute) return;
    const root = scrollArea.current;
    const target = searchTarget.target
      ? Array.from(root?.querySelectorAll<HTMLElement>("h2, label, summary, [aria-label]") ?? [])
        .find(element => element.textContent?.trim() === searchTarget.target || element.getAttribute("aria-label") === searchTarget.target)
      : root?.querySelector<HTMLElement>("h1");
    if (!target) return;
    target.tabIndex = -1;
    target.focus({ preventScroll: true });
    if (searchTarget.target) {
      const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      target.scrollIntoView({ block: "center", behavior: reducedMotion ? "auto" : "smooth" });
      if (!reducedMotion) {
        target.classList.remove("settings-search-target-pulse");
        void target.offsetWidth;
        target.classList.add("settings-search-target-pulse");
        target.addEventListener("blur", () => target.classList.remove("settings-search-target-pulse"), { once: true });
      }
    }
    setSearchTarget(null);
  }, [searchTarget, activePage, state, waitingForRoute]);

  return (
    <div className="settings-window">
      <Titlebar
        pageLabel={state?.onboardingRequired || state?.practiceState?.open ? undefined : info.label}
        onClose={() => { cancelSearchNavigation(); controller.setClosing(true); }}
        onError={controller.setError}
      />
      {state?.onboardingRequired ? <OnboardingPage controller={{ ...controller, state }} /> : state?.practiceState?.open ? <DictationPractice controller={{ ...controller, state }} /> : <div className="app">
        <aside>
          <SettingsNavigation pages={visiblePages} activePage={activePage}
            version={state?.applicationVersion} onNavigate={async id => { cancelSearchNavigation(); await controller.navigate(id); }}
            onSearchInteraction={cancelSearchNavigation}
            onSearchNavigate={result => { setSearchTarget({ ...result, generation: ++searchGeneration.current }); void controller.navigate(result.page.id); }} />
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
      </div>}
      <SettingsDialogs controller={controller} />
    </div>
  );
}
