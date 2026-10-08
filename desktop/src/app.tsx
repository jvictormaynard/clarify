import { useLayoutEffect, useRef } from "react";
import { AlertCircle, LoaderCircle } from "lucide-react";
import { Titlebar } from "./components/titlebar";
import { Button } from "./components/ui";
import { GeneralPage } from "./pages/general-page";
import { DictationPage } from "./pages/dictation-page";
import { TextPage } from "./pages/text-page";
import { DictionaryPage } from "./pages/dictionary-page";
import { ShortcutsPage } from "./pages/shortcuts-page";
import { ModelsPage } from "./pages/models-page";
import { settingsPages } from "./settings/navigation";
import { SettingsDialogs } from "./settings/settings-dialogs";
import { useSettings } from "./settings/use-settings";

const pageComponents = {
  general: GeneralPage,
  dictation: DictationPage,
  text: TextPage,
  dictionary: DictionaryPage,
  shortcuts: ShortcutsPage,
  models: ModelsPage,
};

export function App() {
  const controller = useSettings();
  const { state, page, error, busy, navigating, dirty, saved } = controller;
  const scrollArea = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (scrollArea.current) scrollArea.current.scrollTop = 0;
  }, [page]);
  const Page = pageComponents[page];
  const info = settingsPages.find((item) => item.id === page)!;

  return (
    <div className="settings-window">
      <Titlebar
        onClose={() => controller.setClosing(true)}
        onError={controller.setError}
      />
      <div className="app" data-navigating={navigating || undefined}>
        <aside>
          <nav aria-label="Configurações">
            {settingsPages.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                disabled={busy}
                aria-label={label}
                aria-current={id === page ? "page" : undefined}
                onClick={() => void controller.navigate(id)}
              >
                <Icon size={18} strokeWidth={1.6} />
                <span>{label}</span>
              </button>
            ))}
          </nav>
        </aside>
        <main>
          <div className="scroll-area" ref={scrollArea}>
            <header>
              <h1>{info.label}</h1>
            </header>
            <div className="page">
              {error && (
                <div role="alert" className="error settings-error">
                  <AlertCircle size={17} />
                  <span>{error}</span>
                </div>
              )}
              {!state ? (
                <div className="connection" role="status">
                  <LoaderCircle className="spin" size={22} />
                  Conectando ao Clarify…
                </div>
              ) : (
                <fieldset disabled={busy}>
                  <Page controller={{ ...controller, state }} />
                </fieldset>
              )}
            </div>
          </div>
          <div
            className="floating-save"
            role="group"
            aria-label="Alterações pendentes"
            aria-hidden={!dirty}
            data-visible={dirty || undefined}
          >
            <Button
              variant="ghost"
              disabled={busy || !dirty}
              onClick={() => controller.setDiscarding(true)}
            >
              Descartar
            </Button>
            <Button
              variant="primary"
              aria-label="Salvar alterações"
              disabled={busy || !dirty || !state}
              onClick={() => void controller.save()}
            >
              {busy && !navigating ? (
                <LoaderCircle size={15} className="spin" />
              ) : null}
              Salvar
            </Button>
          </div>
          <span className="sr-only" role="status">
            {saved ? "Alterações salvas" : ""}
          </span>
        </main>
        <SettingsDialogs controller={controller} />
      </div>
    </div>
  );
}
