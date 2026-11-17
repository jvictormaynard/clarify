import "../styles/onboarding.css";
import { t } from "../i18n";
import { useEffect, useRef, useState } from "react";
import { ArrowLeft, HardDrive, Mic, Smartphone } from "lucide-react";
import { ClarifyLogo } from "../components/clarify-logo";
import { Button, Field, Picker, SettingsDisclosure } from "../components/ui";
import { ChatGPTPlan } from "../components/chatgpt-plan";
import type { SettingsPageProps } from "../settings/use-settings";

const steps = ["welcome", "language", "speech", "text", "install"] as const;
type Step = typeof steps[number];
export function OnboardingPage({ controller }: SettingsPageProps) {
  const { state, busy, error, run } = controller;
  const setup = state.personalSetupState;
  const speechIds = state.localModelIds || [];
  const [step, setStep] = useState<Step>("welcome");
  const [language, setLanguage] = useState(setup?.language || "auto");
  const [speech, setSpeech] = useState("");
  const [provider, setProvider] = useState("none");
  const [model, setModel] = useState("");
  const [saving, setSaving] = useState(false);
  const [endpointOpen, setEndpointOpen] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const browsedSpeech = useRef("");
  const recommendation = setup?.recommendation;
  const speechModel = speech || recommendation?.modelId || "";
  const selected = setup?.textOptions.find(option => option.id === provider);
  const textError = error || setup?.error || (provider === "chatgpt" && (state.chatgptState?.error || state.providerError)) || (provider === state.selectedProviderId && state.providerError) || "";
  useEffect(() => {
    if (["opencode", "chatgpt"].includes(provider) && !model && selected?.models?.length) setModel(selected.models[0].id);
  }, [provider, model, selected?.models]);
  const pending = busy || !!setup?.busy || saving || state.providerBusy || controller.validatingProvider;
  useEffect(() => {
    if (step !== "speech") { browsedSpeech.current = ""; return; }
    if (speechModel && !pending && speechIds[state.localProfileIndex] !== speechModel && browsedSpeech.current !== speechModel) {
      browsedSpeech.current = speechModel;
      void run("selectLocalProfile", speechIds.indexOf(speechModel));
    }
  }, [step, speechModel, pending, speechIds, state.localProfileIndex, run]);
  const installed = state.localAsrStatus === "installed" && speechIds[state.localProfileIndex] === speechModel || (!speech && !!recommendation?.installed);
  const options = { language, speechModelId: speechModel, textProvider: provider, textModelId: model || selected?.modelId || "" };
  const textReady = provider === "none" || !!(selected?.connected && options.textModelId &&
    (!["chatgpt", "opencode"].includes(provider) || selected.models?.some(item => item.id === options.textModelId)));
  useEffect(() => { heading.current?.focus(); heading.current?.closest("main")?.scrollTo({ top: 0 }); }, [step]);
  const command = (action: "recommend" | "configure" | "complete" | "connect_opencode" | "cancel" | "reset_text_choice") => run("personalSetupCommand", action, JSON.stringify(options));
  const next = async () => {
    if (pending) return;
    if (step === "language") { setSpeech(""); await command("recommend"); }
    if (step === "speech") await run("selectLocalProfile", speechIds.indexOf(speechModel));
    if (step === "install") {
      setSaving(true);
      try { await command("complete"); } finally { setSaving(false); }
      return;
    }
    setStep(steps[steps.indexOf(step) + 1]);
  };
  const selectText = async (value: string) => {
    if (!await command("reset_text_choice")) return;
    controller.setApiKey(""); controller.setEndpoint(null);
    setProvider(value); setModel("");
    if (!["none", "opencode"].includes(value)) {
      await controller.selectProvider(value);
      await run("selectWorkflow", "local_asr_refinement");
    }
  };
  const skipText = async () => {
    if (pending) return;
    if (!await command("reset_text_choice")) return;
    controller.setApiKey(""); controller.setEndpoint(null);
    setProvider("none"); setModel("");
    setStep("install");
  };
  const titles: Record<Step, string> = { welcome: "Boas-vindas ao Clarify", language: "setup_languages", speech: "setup_speech", text: "setup_text", install: "setup_install" };
  return <main className="onboarding onboarding-page onboarding-flow personal-setup" data-step={step}>
    <div className="onboarding-content">
      <div className="setup-progress" role="progressbar" aria-label={t("setup_progress")}
        aria-valuemin={1} aria-valuemax={steps.length} aria-valuenow={steps.indexOf(step) + 1}>
        {steps.map((item, index) => <span key={item} aria-hidden="true" data-active={item === step} data-complete={index < steps.indexOf(step)} />)}
      </div>
      <div className="onboarding-heading">
        {step === "welcome" && <ClarifyLogo />}
        <h1 ref={heading} tabIndex={-1}>{t(titles[step])}</h1>
        <p className="hint">{t({ welcome: "setup_welcome_hint", language: "setup_language_hint", speech: "setup_speech_hint", text: "setup_text_hint", install: "setup_install_hint" }[step])}</p>
      </div>
      <div className="setup-body">
        {step !== "text" && (error || setup?.error) && <p className="error setup-error" role="alert">{t(error || setup?.error || "")}</p>}
        {step === "welcome" && <div className="setup-benefits"><p><Mic aria-hidden="true" />{t("setup_voice")}</p><p><HardDrive aria-hidden="true" />{t("setup_private")}</p><p><Smartphone aria-hidden="true" />{t("setup_phone")}</p></div>}
        {step === "language" && <Picker label={t("setup_languages")} value={language} options={state.languages.map((id, index) => ({ id, label: state.languages[index] === "auto" ? t("setup_auto_language") : new Intl.DisplayNames([state.uiLanguage || "en"], { type: "language" }).of(id) || id }))} onChange={setLanguage} disabled={pending} />}
        {step === "speech" && <>
          <div className="setup-recommendation setup-speech-card">
            <div className="setup-model-icon"><Mic aria-hidden="true" size={24} /></div>
            {speechModel === recommendation?.modelId && <span className="badge">{t("setup_recommended")}</span>}
            <h2>{state.localProfiles[speechIds.indexOf(speechModel)] || recommendation?.label}</h2>
            <p>{t("setup_location")}</p>
            {speechModel === recommendation?.modelId && <p className="hint setup-model-download"><HardDrive aria-hidden="true" size={15} />{t("setup_download", { v0: Math.ceil((recommendation?.downloadBytes || 0) / 1024 / 1024) })}</p>}
          </div>
          {state.localModelDescription && speechIds[state.localProfileIndex] === speechModel && <p className="hint">{t(state.localModelDescription)}</p>}
          <SettingsDisclosure title={t("setup_alternatives")} className="setup-model-options">
            <Picker label={t("setup_speech_model")} value={speechModel} options={state.localProfiles.map((label, index) => ({ id: speechIds[index], label })).filter(option => !!option.id && !["ggml-small", "ggml-medium"].includes(option.id))} disabled={pending} onChange={async id => { setSpeech(id); await run("selectLocalProfile", speechIds.indexOf(id)); }} />
            <p className="hint">{recommendation?.reason}</p>
            <p className="hint">{state.localAsrRequirementsList.join(" · ")}</p>
            <Button variant="text" disabled={pending} onClick={() => void command("recommend")}>{t("setup_check_again")}</Button>
          </SettingsDisclosure>
        </>}
        {step === "text" && <>
          <div className="setup-form-field">
            <p className="setup-field-label">{t("setup_text_service")}</p>
            <Picker label={t("setup_text_service")} value={provider} disabled={pending} options={(setup?.textOptions || []).map(option => ({ id: option.id, label: option.id === "none" ? t("setup_raw") : option.id === "openai" ? "OpenAI" : option.id === "opencode" ? "OpenCode" : t(option.label) }))} onChange={value => void selectText(value)} />
          </div>
          <div className="setup-provider" key={provider}>
            <p className="hint">{t(provider === "none" ? "setup_raw_hint" : provider === "chatgpt" ? "setup_subscription" : provider === "opencode" ? "setup_free" : "setup_key_hint")}</p>
            {textError && <p className="error setup-error" role="alert">{t(textError)}</p>}
            {provider === "chatgpt" && <ChatGPTPlan controller={controller} setup />}
            {provider === "opencode" && <Button variant={selected?.connected ? "default" : "primary"} loading={!!setup?.busy} disabled={pending} onClick={() => void command("connect_opencode")}>{t(selected?.runtimeInstalled ? "setup_connect_free" : "setup_install_opencode")}</Button>}
            {!["none", "chatgpt", "opencode"].includes(provider) && <>
              {provider === "openai" && state.providerSupportsCustomEndpoint && <SettingsDisclosure title={t("setup_custom_endpoint")} className="setup-endpoint" open={endpointOpen} onOpenChange={setEndpointOpen}>
                <Field title={t("Endpoint")} value={controller.endpoint} onChange={event => controller.setEndpoint(event.target.value)} />
                <p className="hint">{t("setup_local_endpoint_hint")}</p>
              </SettingsDisclosure>}
              <Field title={t("Chave de API")} type="password" autoComplete="off" value={controller.apiKey} onChange={event => controller.setApiKey(event.target.value)} />
              <Button variant={selected?.connected ? "default" : "primary"} loading={controller.validatingProvider} disabled={pending || controller.validatingProvider} onClick={() => void controller.validateProvider()}>{t("Validar e salvar chave")}</Button>
            </>}
            {provider !== "none" && selected?.connected && (selected.models?.length ? <div className="setup-form-field"><p className="setup-field-label">{t("setup_text_model")}</p><Picker label={t("setup_text_model")} value={model || selected.modelId || ""} options={selected.models} disabled={pending} onChange={setModel} /></div> : !["chatgpt", "opencode"].includes(provider) && <Field title={t("setup_text_model")} value={model || selected.modelId || ""} onChange={event => setModel(event.target.value)} />)}
          </div>
        </>}
        {step === "install" && <>
          <div className="setup-recommendation"><h2>{state.localProfiles[speechIds.indexOf(speechModel)] || recommendation?.label}</h2><p>{t("setup_location")}</p><p className="hint">{provider === "none" ? t("setup_raw") : `${selected?.label} · ${options.textModelId}`}</p></div>
          <p role="status">{t(state.localAsrDetail || (installed ? "setup_ready" : "setup_needs_install"))}</p>
          {state.localAsrBusy && <progress aria-label={t("setup_install")} max={1} value={state.localAsrProgress > 1 ? state.localAsrProgress / 100 : state.localAsrProgress} />}
          {!pending && !installed && <Button variant="primary" onClick={() => void run("installLocalAsr")}>{t(setup?.error ? "setup_retry_install" : "setup_download_install")}</Button>}
        </>}
      </div>
      <div className="onboarding-flow-actions setup-footer">
        {setup?.busy ? <Button onClick={() => void command("cancel")}>{t("Cancelar")}</Button> : (step !== "install" || installed) && (step !== "text" || textReady) && <Button variant="primary" disabled={pending || !setup} onClick={() => void next()}>{t(step === "welcome" ? "Vamos começar" : step === "install" ? "setup_practice" : "Continuar")}</Button>}
        {step === "text" && provider !== "none" && !setup?.busy && <Button variant="text" disabled={pending} onClick={() => void skipText()}>{t("setup_skip_text")}</Button>}
        {step !== "welcome" && <Button variant="text" disabled={pending} onClick={() => setStep(steps[steps.indexOf(step) - 1])}><ArrowLeft size={16} />{t("Voltar")}</Button>}
      </div>
    </div>
  </main>;
}
