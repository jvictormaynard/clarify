import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Check, Keyboard, Languages, Mail, Mic } from "lucide-react";
import "../styles/onboarding.css";
import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { Button, Picker, Row, Section, TextArea } from "./ui";

const statusMessages: Record<string, string> = {
  practice_busy: "practice_busy",
  practice_configuration: "practice_configuration",
  practice_model: "practice_model",
  practice_session: "practice_session",
  practice_quota: "practice_quota",
  account_allowance_exhausted: "practice_quota",
  account_allocation_waiting: "practice_quota",
  account_authentication_required: "practice_session",
  provider_authentication: "practice_session",
  provider_quota: "Provider quota exceeded. Check your balance or plan.",
  no_audio: "practice_no_audio",
  refinement_failed: "practice_review_failed",
};

export function PracticeEntry({ controller }: SettingsPageProps) {
  return <Section title={t("practice_title")}>
    <Row title={t("practice_optional")} hint={t("practice_repeat_hint")}>
      <Button onClick={() => void controller.run("practiceCommand", "open")}>{t("practice_open")}</Button>
    </Row>
  </Section>;
}

function ShortcutKeys({ shortcut }: { shortcut?: string }) {
  return <span className="onboarding-keys">{(shortcut || t("Definir atalho")).split("+").map((key, index) => <kbd key={index}>{key.trim()}</kbd>)}</span>;
}

export function DictationPractice({ controller }: SettingsPageProps) {
  const { state, run, navigate, error, busy, setCapture } = controller;
  const practice = state.practiceState;
  const [step, setStep] = useState<"setup" | "practice">("setup");
  const heading = useRef<HTMLHeadingElement>(null);
  const recording = practice?.phase === "recording";
  const waiting = practice?.phase === "waiting";
  const processing = practice?.phase === "processing" || waiting;
  const active = recording || processing;
  const success = practice?.phase === "completed" && !!practice.text?.trim() && !practice.status && !practice.blocked;
  // A native shortcut can start capture before the setup button is used.
  const phase = active ? "practice" : success ? "success" : step;
  const shortcut = state.hotkeyActions.find(action => action.id === "recording_hotkey")?.display;
  const command = (action: "start" | "stop" | "cancel" | "close") => void run("practiceCommand", action);
  const testBusy = useRef(state.microphoneTestBusy);
  testBusy.current = state.microphoneTestBusy;
  useEffect(() => {
    void run("refreshMicrophones");
    return () => { if (testBusy.current) void run("stopMicrophoneTest"); };
  }, []);
  useEffect(() => {
    if (active) setStep("practice");
  }, [active]);
  useEffect(() => {
    heading.current?.closest("main")?.scrollTo({ top: 0 });
    heading.current?.focus({ preventScroll: true });
  }, [phase]);
  const leaveSetup = async () => {
    if (state.microphoneTestBusy) await run("stopMicrophoneTest");
    setStep("practice");
  };
  const configure = async () => {
    await run("practiceCommand", "close");
    await navigate(practice?.blocked === "practice_model" ? "models" : practice?.blocked === "practice_session" || state.accountState?.managed || state.accountState?.signedIn ? "account" : "models");
  };
  const status = (!active && practice?.blocked) || practice?.status || (practice?.phase === "microphone_unavailable" ? "practice_microphone" : "");
  const statusKey = status === "provider_authentication" && !state.accountState?.managed && !state.accountState?.signedIn
    ? "practice_configuration" : statusMessages[status] || (status === "practice_microphone" ? "practice_microphone" : "practice_failed");
  const configurationRequired = ["practice_configuration", "practice_model", "practice_session", "practice_quota", "account_allowance_exhausted", "account_allocation_waiting", "account_authentication_required", "provider_authentication", "provider_quota"].includes(status);
  const languages: Record<string, string> = { auto: t("Idioma original"), en: "English", pt: "Português", es: "Español", de: "Deutsch", ru: "Русский" };

  return <main className="onboarding onboarding-page onboarding-flow" data-phase={phase}>
    <div className="onboarding-content" key={phase}>
      <div className="onboarding-heading">
        {success && <div className="onboarding-success-icon"><Check size={32} aria-hidden="true" /></div>}
        <h1 ref={heading} tabIndex={-1}>{t(phase === "setup" ? "Vamos preparar seu ditado" : success ? "Seu ditado está pronto" : "Fale em vez de digitar")}</h1>
        <p className="hint">{t(phase === "setup" ? "Três ajustes. Depois, experimente sua voz." : success ? "Use o atalho onde você pode digitar." : "Experimente aqui. Este e-mail não será enviado.")}</p>
      </div>
      {phase === "setup" ? <div className="onboarding-setup">
        <div className="onboarding-setup-row">
          <div className="onboarding-row-title"><Mic size={18} aria-hidden="true" /><h2>{t("Microfone")}</h2></div>
          <Picker label={t("Microfone")} value={state.selectedMicrophoneId || ""} options={state.microphoneDevices}
            busy={state.microphoneInventoryBusy} disabled={state.microphoneTestBusy || state.microphoneInventoryBusy || busy} onChange={id => void run("selectMicrophone", id)} />
          <div className="onboarding-test-actions">
            <Button disabled={busy || state.microphoneInventoryBusy} onClick={() => void run(state.microphoneTestBusy ? "stopMicrophoneTest" : "testMicrophone")}>
              {t(state.microphoneTestBusy ? "Parar teste" : "Testar microfone")}
            </Button>
            {state.microphoneTestBusy && <meter min="0" max="1" value={state.microphoneTestLevel} aria-label={t("practice_level")} />}
          </div>
          <p className="hint">{t("Teste local de até 30 segundos. O áudio não é enviado.")}</p>
          <p className="hint" role="status">{t(state.microphoneTestStatus || state.microphoneStatus)}</p>
        </div>
        <div className="onboarding-setup-row">
          <div className="onboarding-row-title"><Keyboard size={18} aria-hidden="true" /><h2>{t("Atalho de ditado")}</h2></div>
          <div className="onboarding-shortcut-row"><ShortcutKeys shortcut={shortcut} /><Button variant="text" disabled={busy} onClick={() => setCapture("recording_hotkey")}>{t("Alterar atalho")}</Button></div>
          <p className="hint">{t(state.hotkeyActivationMode === "push_to_talk" ? "Segure para falar. Solte para concluir." : "Pressione para falar. Pressione novamente para concluir.")}</p>
        </div>
        <div className="onboarding-setup-row">
          <div className="onboarding-row-title"><Languages size={18} aria-hidden="true" /><h2>{t("Idioma do texto")}</h2></div>
          <Picker label={t("Idioma do texto")} value={state.language} options={state.languages.map(id => ({ id, label: languages[id] || id }))}
            disabled={busy} onChange={value => void run("setLanguage", value)} />
        </div>
      </div> : <>
        {success && <div className="onboarding-confetti" aria-hidden="true">{Array.from({ length: 12 }, (_, index) => <i key={index} style={{ "--piece": index } as CSSProperties} />)}</div>}
        <div className={`onboarding-composer${recording ? " is-recording" : ""}`} tabIndex={0} role="group" aria-label={t("E-mail de prática")}>
          <div className="onboarding-composer-header"><Mail size={16} aria-hidden="true" /><span>{t("E-mail de prática")}</span></div>
          <div className="onboarding-composer-subject">{t("Assunto: uma conversa rápida")}</div>
          <div className="onboarding-composer-body">
            {practice?.text ? <label>{t("practice_result")}<TextArea readOnly value={practice.text} rows={4} /></label> : <>
              <ShortcutKeys shortcut={shortcut} />
              <p>{shortcut ? t(state.hotkeyActivationMode === "push_to_talk" ? "practice_hold" : "practice_toggle", { shortcut }) : t("practice_button_hint")}</p>
              <p className="hint">{t("practice_phrase")}</p>
            </>}
            {active && <p className="onboarding-capture-status" role="status"><Mic size={16} aria-hidden="true" />{t(recording ? "practice_recording" : waiting ? "practice_waiting" : "practice_processing")}</p>}
          </div>
        </div>
        <p className="hint onboarding-destination">{t("practice_destination")}</p>
      </>}
      {(error || (status && status !== "practice_busy")) && <p role="status" className="onboarding-feedback">{error ? t(error) : t(statusKey)}</p>}
      <div className="onboarding-flow-actions">
        {phase === "setup" ? <Button variant="primary" disabled={busy || state.microphoneInventoryBusy} onClick={() => void leaveSetup()}>{t("Continuar")}</Button>
          : success ? <><Button variant="primary" onClick={() => command("close")}>{t("practice_done")}</Button><Button variant="text" disabled={busy} onClick={() => command("start")}>{t("practice_again")}</Button></>
          : <>
            <Button variant="primary" disabled={busy || processing || (!recording && !!practice?.blocked)} onClick={() => command(recording ? "stop" : "start")}>
              {t(processing ? waiting ? "practice_waiting" : "practice_processing" : recording ? "practice_stop" : "practice_start")}
            </Button>
            {active ? <Button onClick={() => command("cancel")}>{t("Cancelar")}</Button> : <Button variant="text" onClick={() => setStep("setup")}>{t("Voltar")}</Button>}
          </>}
        {!active && !success && configurationRequired && <Button onClick={() => void configure()}>{t(practice?.blocked === "practice_model" ? "Configurar modelo" : "practice_configure")}</Button>}
        {!success && <Button variant="text" onClick={() => command("close")}>{t("practice_skip")}</Button>}
      </div>
    </div>
  </main>;
}
