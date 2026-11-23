import { DictationPermissions } from "./dictation-permissions";
import { InputMonitoringButton } from "./input-monitoring-button";
import { shortcutKeyName } from "../settings/display-labels";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Check, Keyboard, Languages, Mail, Mic, Smartphone } from "lucide-react";
import "../styles/onboarding.css";
import "../styles/onboarding-practice.css";
import { t } from "../i18n";
import { writingStyleOptions } from "../settings/writing-style-options";
import type { WritingStyle } from "../settings/bridge";
import type { SettingsPageProps } from "../settings/use-settings";
import { Button, Input, Picker, Row, Section, TextArea } from "./ui";

const statusMessages: Record<string, string> = {
  practice_busy: "practice_busy",
  practice_permissions: "practice_permissions",
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
  return <span className="onboarding-keys">{(shortcut || t("Definir atalho")).split("+").map((key, index) => <kbd key={index}>{shortcutKeyName(key.trim())}</kbd>)}</span>;
}

function PracticeProgress({ step, total = 3 }: { step: number; total?: number }) {
  return <div className="onboarding-practice-progress" aria-hidden="true">
    {Array.from({ length: total }, (_, index) => <span key={index} data-active={index === step} data-complete={index < step} />)}
  </div>;
}

export function DictationPractice({ controller }: SettingsPageProps) {
  const { state, run, navigate, error, busy, setCapture } = controller;
  const practice = state.practiceState;
  const guided = !!state.dictationPermissions?.accessibility;
  const [step, setStep] = useState<"permissions" | "setup" | "microphone" | "language" | "shortcut" | "practice">(
    guided ? "permissions" : "setup",
  );
  const [backward, setBackward] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const recording = practice?.phase === "recording";
  const waiting = practice?.phase === "waiting";
  const processing = practice?.phase === "processing" || waiting;
  const active = recording || processing;
  const success = practice?.phase === "completed" && !!practice.text?.trim() && !practice.status && !practice.blocked;
  // A native shortcut can start capture before the setup button is used.
  const phase = active ? "practice" : success ? "success" : step;
  const recordingShortcut = state.hotkeyActions.find(action => action.id === "recording_hotkey");
  const shortcut = recordingShortcut?.key ? recordingShortcut.display : undefined;
  const shortcutUnavailable = !!shortcut && state.hotkeyUnavailable?.includes(shortcut);
  const listeningForShortcut = practice?.shortcutTest === "listening" && !state.hotkeyCaptureAction;
  const [phone, setPhone] = useState(false);
  const close = () => void run("practiceCommand", "done");

  const testBusy = useRef(state.microphoneTestBusy);
  testBusy.current = state.microphoneTestBusy;
  useEffect(() => {
    if (phase === "setup" || phase === "microphone") void run("refreshMicrophones");
  }, [phase, run]);
  useEffect(() => () => { if (testBusy.current) void run("stopMicrophoneTest"); }, [run]);
  useEffect(() => {
    if (active) setStep("practice");
  }, [active]);
  useEffect(() => {
    heading.current?.closest("main")?.scrollTo({ top: 0 });
    heading.current?.focus({ preventScroll: true });
  }, [phase, phone]);
  const leaveMicrophone = async () => {
    if (state.microphoneTestBusy && !await run("stopMicrophoneTest")) return;
    setBackward(false);
    setStep(guided ? "language" : "practice");
  };
  useEffect(() => {
    if (phase === "shortcut" && !state.hotkeyCaptureAction) void run("practiceCommand", "test-shortcut");
  }, [phase, shortcut, state.hotkeyCaptureAction, run]);
  const beginShortcutTest = () => {
    setBackward(false);
    setStep("shortcut");
  };
  const continueSetup = async () => {
    if (phase === "setup" || phase === "microphone") await leaveMicrophone();
    else if (phase === "language") beginShortcutTest();
    else if (phase === "shortcut") {
      if (!await run("practiceCommand", "finish-shortcut")) return;
      setBackward(false);
      setStep("practice");
    } else setPhone(true);
  };
  const goBack = async () => {
    if (phase === "shortcut" && !await run("practiceCommand", "leave-shortcut")) return;
    if (phase === "microphone" && state.microphoneTestBusy && !await run("stopMicrophoneTest")) return;
    setBackward(true);
    setStep(phase === "shortcut" ? "language" : phase === "language" ? "microphone" : "permissions");
  };
  const configure = async () => {
    await run("practiceCommand", "close");
    await navigate(practice?.phase === "microphone_unavailable" ? "dictation" : practice?.blocked === "practice_model" ? "models" : practice?.blocked === "practice_session" || state.accountState?.managed ? "account" : "models");
  };
  const status = (!active && practice?.blocked) || practice?.status || (practice?.phase === "microphone_unavailable" ? "practice_microphone" : "");
  const statusKey = status === "provider_authentication" && !state.accountState?.managed
    ? "practice_configuration" : statusMessages[status] || (status === "practice_microphone" ? "practice_microphone" : "practice_failed");
  const configurationRequired = ["practice_microphone", "practice_configuration", "practice_model", "practice_session", "practice_quota", "account_allowance_exhausted", "account_allocation_waiting", "account_authentication_required", "provider_authentication", "provider_quota"].includes(status);
  const languages: Record<string, string> = { auto: t("Idioma original"), en: "English", pt: "Português", es: "Español", de: "Deutsch", ru: "Русский" };

  if (phase === "permissions") return <DictationPermissions controller={controller}
    progress={<PracticeProgress step={0} total={5} />}
    onContinue={() => {
      setBackward(false);
      setStep("microphone");
    }} onSkip={close} />;
  if (phone) return <main className="onboarding onboarding-page onboarding-flow onboarding-practice" data-phase="phone">
    <div className="onboarding-content">
      <PracticeProgress step={guided ? 4 : 2} total={guided ? 5 : 3} />
      <div className="onboarding-heading">
        <div className="onboarding-practice-symbol" aria-hidden="true"><Smartphone size={24} /></div>
        <h1 ref={heading} tabIndex={-1}>{t("setup_phone_title")}</h1>
        <p className="hint">{t("setup_phone_hint")}</p>
      </div>
      <div className="onboarding-flow-actions onboarding-practice-footer">
        <Button variant="primary" onClick={async () => {
          if (await run("practiceCommand", "done")) await navigate("devices");
        }}>{t("setup_pair_phone")}</Button>
        <Button variant="text" onClick={close}>{t("practice_skip")}</Button>
        <Button variant="text" onClick={() => setPhone(false)}>{t("Voltar")}</Button>
      </div>
    </div>
  </main>;
  const setupPhase = ["setup", "microphone", "language", "shortcut"].includes(phase);
  const stepIndex = { permissions: 0, setup: 0, microphone: 1, language: 2, shortcut: 3, practice: 4, success: 4 }[phase];
  const title = { permissions: "Permissões para ditar", setup: "Vamos preparar seu ditado", microphone: "Teste o microfone",
    language: "Escolha o idioma", shortcut: "Teste o atalho", practice: "Fale em vez de digitar", success: "Seu ditado está pronto" }[phase];
  const hint = { permissions: "", setup: "practice_setup_hint", microphone: "Fale e confira o nível de áudio.",
    language: "O Clarify usa este ajuste para o texto ditado.", shortcut: "Use o atalho abaixo para confirmar que o Clarify o reconhece.",
    practice: "Experimente aqui. Este e-mail não será enviado.", success: "Use o atalho onde você pode digitar." }[phase];

  return <main className="onboarding onboarding-page onboarding-flow onboarding-practice" data-phase={phase}
    data-guided={guided} data-backward={backward}>
    <div className="onboarding-content" key={phase}>
      <PracticeProgress step={guided ? stepIndex : phase === "setup" ? 0 : 1} total={guided ? 5 : 3} />
      <div className="onboarding-heading">
        {success && <div className="onboarding-success-icon"><Check size={32} aria-hidden="true" /></div>}
        <h1 ref={heading} tabIndex={-1}>{t(title)}</h1>
        {!recording && <p className="hint">{t(hint)}</p>}
      </div>
      {setupPhase ? <div className="onboarding-setup">
        {(phase === "setup" || phase === "microphone") && <div className="onboarding-setup-row">
          <h2><Mic size={18} aria-hidden="true" />{t("Microfone")}</h2>
          <div className="onboarding-setup-controls">
            <div className="onboarding-microphone-controls">
              <Picker label={t("Microfone")} value={state.selectedMicrophoneId || ""} options={state.microphoneDevices}
                busy={state.microphoneInventoryBusy} disabled={state.microphoneTestBusy || state.microphoneInventoryBusy || busy} onChange={id => void run("selectMicrophone", id)} />
              <Button aria-label={t(state.microphoneTestBusy ? "Parar teste" : "Testar microfone")} aria-describedby="practice-microphone-privacy"
                title={t("Teste local de até 30 segundos. O áudio não é enviado.")}
                disabled={busy || state.microphoneInventoryBusy} onClick={() => void run(state.microphoneTestBusy ? "stopMicrophoneTest" : "testMicrophone")}>
                {t(state.microphoneTestBusy ? "Parar teste" : "Testar microfone")}
              </Button>
            </div>
            <p id="practice-microphone-privacy" className="sr-only">{t("Teste local de até 30 segundos. O áudio não é enviado.")}</p>
            {state.microphoneTestBusy && <meter min="0" max="1" value={state.microphoneTestLevel} aria-label={t("practice_level")} />}
            <p className="hint" role="status">{t(state.microphoneTestStatus || state.microphoneStatus)}</p>
          </div>
        </div>}
        {(phase === "setup" || phase === "shortcut") && <div className="onboarding-setup-row">
          <h2><Keyboard size={18} aria-hidden="true" />{t("Atalho de ditado")}</h2>
          <div className="onboarding-setup-controls">
            <div className="onboarding-shortcut-row"><ShortcutKeys shortcut={shortcut} /><Button variant="text" disabled={busy} onClick={async event => {
              const opener = event.currentTarget;
              if (guided && !await run("practiceCommand", "leave-shortcut")) return;
              setCapture("recording_hotkey", opener);
            }}>{t("Alterar atalho")}</Button></div>
            {(state.inputMonitoringStatus === "request" || state.inputMonitoringStatus === "settings") && <>
              <p className="hint">{t("Reconhece seu atalho mesmo quando outro app está aberto.")}</p>
              <InputMonitoringButton controller={controller} disabled={busy} />
            </>}
            <p className="hint">{t(state.hotkeyActivationMode === "push_to_talk" ? "Segure para falar. Solte para concluir." : "Pressione para falar. Pressione novamente para concluir.")}</p>
            {phase === "shortcut" && (shortcutUnavailable || listeningForShortcut) &&
              <p className="hint" role="status">{t(shortcutUnavailable
                ? "Este atalho está indisponível. Confira as permissões ou escolha outro atalho."
                : "Aguardando seu atalho")}</p>}
            {phase === "shortcut" && !shortcutUnavailable && practice?.shortcutTest === "passed" &&
              <p className="practice-shortcut-passed" role="status"><Check size={16} aria-hidden="true" />{t("Atalho reconhecido")}</p>}
          </div>
        </div>}
        {(phase === "setup" || phase === "language") && <div className="onboarding-setup-row">
          <h2><Languages size={18} aria-hidden="true" />{t("Idioma do texto")}</h2>
          <div className="onboarding-setup-controls">
            <Picker label={t("Idioma do texto")} value={state.language} options={state.languages.map(id => ({ id, label: languages[id] || id }))}
              disabled={busy} onChange={value => void run("setLanguage", value)} />
          </div>
        </div>}
        {(phase === "setup" || phase === "language") && state.writingStyleRefinementAllowed !== false && <div className="onboarding-setup-row">
          <h2>{t("Tom")}</h2>
          <div className="onboarding-setup-controls">
            <Picker label={t("Tom")} value={state.dictationWritingStyle ?? ""} options={writingStyleOptions(state.dictationWritingStyle ?? "")}
              disabled={busy} onChange={value => void run("setDictationWritingStyle", value as WritingStyle | "")} />
          </div>
        </div>}
      </div> : <>
        {success && <div className="onboarding-confetti" aria-hidden="true">{Array.from({ length: 12 }, (_, index) => <i key={index} style={{ "--piece": index } as CSSProperties} />)}</div>}
        <div className={`onboarding-composer${recording ? " is-recording" : ""}`} tabIndex={0} role="group" aria-label={t("E-mail de prática")}>
          <div className="onboarding-composer-header"><Mail size={16} aria-hidden="true" /><span>{t("E-mail de prática")}</span></div>
          <label className="onboarding-composer-subject">
            <span>{t("practice_subject_label")}:</span>
            <Input unstyled aria-label={t("practice_subject_label")} readOnly value={t("practice_subject_text")} />
          </label>
          <div className="onboarding-composer-body">
            {recording ? <>
              <p className="hint">{t("practice_read_instruction")}</p>
              <p className="onboarding-reading" aria-live="polite"><q><em>{t("practice_read_text")}</em></q></p>
            </> : processing ?
              <p role="status">{t(waiting ? "practice_waiting" : "practice_processing")}</p> : practice?.text ?
              <TextArea unstyled shellClassName="w-full" className="resize-none" aria-label={t("practice_result")} readOnly value={practice.text} rows={4} /> : <>
              <ShortcutKeys shortcut={shortcut} />
              <p>{shortcut ? t(state.hotkeyActivationMode === "push_to_talk" ? "practice_shortcut_hold" : "practice_shortcut_toggle", { shortcut }) : t("Definir atalho")}</p>
            </>}
          </div>
        </div>
        {recording ? <p className="onboarding-capture-status" role="status"><Mic size={16} aria-hidden="true" />{t("practice_recording")}</p> : <p className="hint onboarding-destination">{t("practice_destination")}</p>}
      </>}
      {(error || (status && status !== "practice_busy")) && <p role="status" className="onboarding-feedback">
        <span>{error ? t(error) : t(statusKey)}</span>
        {!active && status === "practice_permissions" &&
          <Button variant="text" onClick={() => setStep("permissions")}>{t("Permissões para ditar")}</Button>}
        {!active && !success && configurationRequired && <> <a href={practice?.blocked === "practice_model" ? "#models" : "#settings"} onClick={event => { event.preventDefault(); void configure(); }}>{t(practice?.blocked === "practice_model" ? "Configurar modelo" : "practice_configure")}</a></>}
      </p>}
      <div className="onboarding-flow-actions onboarding-practice-actions onboarding-practice-footer">
        <Button variant="primary" disabled={setupPhase
          ? busy || state.microphoneInventoryBusy || (phase === "setup" && !shortcut)
            || (phase === "shortcut" && (shortcutUnavailable || practice?.shortcutTest !== "passed"))
          : busy || !success}
          onClick={() => void continueSetup()}>{t("Continuar")}</Button>
        {guided && setupPhase && <Button variant="text" disabled={busy} onClick={() => void goBack()}>{t("Voltar")}</Button>}
        <Button variant="text" onClick={close}>{t("practice_skip")}</Button>
      </div>
    </div>
  </main>;
}
