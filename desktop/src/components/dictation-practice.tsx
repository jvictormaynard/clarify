import { useEffect } from "react";
import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { Button, Picker, Row, Section, TextArea } from "./ui";
import { ClarifyLogo } from "./clarify-logo";

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

export function DictationPractice({ controller }: SettingsPageProps) {
  const { state, run, navigate, error, busy } = controller;
  const practice = state.practiceState;
  const recording = practice?.phase === "recording";
  const waiting = practice?.phase === "waiting";
  const processing = practice?.phase === "processing" || waiting;
  const active = recording || processing;
  const shortcut = state.hotkeyActions.find(action => action.id === "recording_hotkey")?.display;
  const command = (action: "start" | "stop" | "cancel" | "close") => void run("practiceCommand", action);
  useEffect(() => { void run("refreshMicrophones"); }, []);
  const configure = async () => {
    await run("practiceCommand", "close");
    await navigate(practice?.blocked === "practice_session" || state.accountState?.managed || state.accountState?.signedIn ? "account" : "models");
  };
  const status = (!active && practice?.blocked) || practice?.status || (practice?.phase === "microphone_unavailable" ? "practice_microphone" : "");
  const statusKey = status === "provider_authentication" && !state.accountState?.managed && !state.accountState?.signedIn
    ? "practice_configuration" : statusMessages[status] || (status === "practice_microphone" ? "practice_microphone" : "practice_failed");

  return <main className="onboarding onboarding-page">
    <div className="onboarding-content">
      <div className="onboarding-heading">
        <ClarifyLogo />
        <h1>{t("practice_title")}</h1>
        <p className="hint">{t("practice_optional")}</p>
      </div>
      <div className="onboarding-panel">
        <p className="hint">{t("practice_destination")}</p>
        <Row title={t("Microfone")}>
          <Picker label={t("Microfone")} value={state.selectedMicrophoneId || ""}
            options={state.microphoneDevices} disabled={active || state.microphoneTestBusy || busy}
            onChange={id => void run("selectMicrophone", id)} />
        </Row>
        <p className="hint">{t(state.microphoneStatus)}</p>
        <Button disabled={active || busy || state.microphoneInventoryBusy}
          onClick={() => void run(state.microphoneTestBusy ? "stopMicrophoneTest" : "testMicrophone")}>
          {t(state.microphoneTestBusy ? "Parar teste" : "Testar microfone")}
        </Button>
        {state.microphoneTestBusy && <meter min="0" max="1" value={state.microphoneTestLevel} aria-label={t("practice_level")} />}
        {state.microphoneTestStatus && <p className="hint" role="status">{t(state.microphoneTestStatus)}</p>}
        <p>{shortcut ? t(state.hotkeyActivationMode === "push_to_talk" ? "practice_hold" : "practice_toggle", { shortcut }) : t("practice_button_hint")}</p>
        <p className="hint">{t("practice_phrase")}</p>
        {(error || status) && <p role="status" className="hint">{error ? t(error) : t(statusKey)}</p>}
        {active && <p role="status">{t(recording ? "practice_recording" : waiting ? "practice_waiting" : "practice_processing")}</p>}
        {practice?.text && <>
          <label>{t("practice_result")}<TextArea readOnly value={practice.text} rows={4} /></label>
          <p className="hint">{t("practice_result_hint")}</p>
        </>}
        {processing ? <Button disabled>{t(waiting ? "practice_waiting" : "practice_processing")}</Button> : <Button variant="primary"
          disabled={busy || (!recording && !!practice?.blocked)} onClick={() => command(recording ? "stop" : "start")}>
          {t(recording ? "practice_stop" : practice?.text ? "practice_again" : "practice_start")}
        </Button>}
        {active && <Button onClick={() => command("cancel")}>{t("Cancelar")}</Button>}
        {!active && (practice?.blocked || status) && <Button onClick={() => void configure()}>{t("practice_configure")}</Button>}
        <Button variant="text" onClick={() => command("close")}>{t(practice?.text ? "practice_done" : "practice_skip")}</Button>
      </div>
    </div>
  </main>;
}
