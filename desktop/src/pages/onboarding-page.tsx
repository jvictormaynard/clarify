import "../styles/onboarding.css";
import { t } from "../i18n";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ArrowLeft, Check, HardDrive, KeyRound, Mic, MoreHorizontal } from "lucide-react";
import { ClarifyLogo } from "../components/clarify-logo";
import { Button, Field, Input, Picker, SettingsDisclosure } from "../components/ui";
import { LanguageWheel } from "../components/language-wheel";
import { Dialog, DialogPopup, DialogHeader, DialogTitle, DialogDescription } from "../components/primitives/dialog";
import { ProviderBrandIcon } from "../components/provider-brand-icon";
import { ChatGPTPlan } from "../components/chatgpt-plan";
import type { SettingsPageProps } from "../settings/use-settings";

const steps = ["language", "welcome", "text", "speech", "install"] as const;
type Step = typeof steps[number];
function chooseRadio(event: KeyboardEvent<HTMLDivElement>) {
  if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  const radios = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('button[role="radio"]:not(:disabled)')];
  const index = radios.indexOf(event.target as HTMLButtonElement);
  if (index < 0) return;
  event.preventDefault();
  const next = event.key === "Home" ? 0 : event.key === "End" ? radios.length - 1 : (index + (["ArrowUp", "ArrowLeft"].includes(event.key) ? -1 : 1) + radios.length) % radios.length;
  radios[next]?.focus(); radios[next]?.click();
}

export function OnboardingPage({ controller }: SettingsPageProps) {
  const { state, busy, error, run } = controller;
  const setup = state.personalSetupState;
  const speechIds = state.localModelIds || [];
  const [step, setStep] = useState<Step>("language");
  const [language, setLanguage] = useState(setup?.language || "auto");
  const [speech, setSpeech] = useState("");
  const [provider, setProvider] = useState("chatgpt");
  const [model, setModel] = useState("");
  const preparedProvider = useRef<string | null>(null);
  const setupChoice = ["openai", "groq", "gemini"].includes(provider) ? "openai" : provider;
  const [saving, setSaving] = useState(false);
  const [endpointOpen, setEndpointOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [connectionOpen, setConnectionOpen] = useState(false);
  const [search, setSearch] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const recommendation = setup?.recommendation;
  const speechModel = speech || recommendation?.modelId || "";
  const browsedSpeechMatches = speechIds[state.localProfileIndex] === speechModel;
  const speechDescription = speechModel === recommendation?.modelId ? recommendation.description : browsedSpeechMatches ? state.localModelDescription : "";
  const speechRequirements = speechModel === recommendation?.modelId ? recommendation.requirementsList || [] : browsedSpeechMatches ? state.localAsrRequirementsList : [];
  const selected = setup?.textOptions.find(option => option.id === provider);
  const textError = error || setup?.error || (provider === "chatgpt" && (state.chatgptState?.error || state.providerError)) || (provider === state.selectedProviderId && state.providerError) || "";
  const catalogKey = provider === "chatgpt" ? `${state.chatgptState?.accountId}:${state.chatgptState?.generation}` : provider;
  const previousCatalog = useRef(catalogKey);
  useEffect(() => {
    if (previousCatalog.current !== catalogKey) { setModel(""); previousCatalog.current = catalogKey; }
    if (selected?.models?.length && !selected.models.some(item => item.id === model)) setModel(selected.models.find(item => item.id === selected.modelId)?.id || selected.models[0].id);
  }, [catalogKey, model, selected?.models]);
  const pending = busy || !!setup?.busy || saving || state.providerBusy || controller.validatingProvider ||
    (step === "speech" && (state.localAsrBusy || state.localBenchmarkBusy));
  const installed = state.localAsrStatus === "installed" && speechIds[state.localProfileIndex] === speechModel || (!speech && !!recommendation?.installed);
  const options = { language, speechModelId: speechModel, textProvider: provider, textModelId: model || selected?.modelId || "" };
  const textReady = provider === "none" || !!(selected?.connected && options.textModelId &&
    (!["chatgpt", "opencode"].includes(provider) || selected.models?.some(item => item.id === options.textModelId)));
  useEffect(() => { heading.current?.focus(); heading.current?.closest("main")?.scrollTo({ top: 0 }); }, [step]);
  const command = (action: "recommend" | "configure" | "complete" | "connect_opencode" | "cancel" | "reset_text_choice") => run("personalSetupCommand", action, JSON.stringify(options));
  const next = async () => {
    if (pending) return;
    if (step === "welcome") {
      if (!await selectText(provider)) return;
      if (provider === "none") { if (await command("recommend")) setStep("speech"); return; }
    }
    if (step === "text" && !await command("recommend")) return;
    if (step === "speech" && !await run("selectLocalProfile", speechIds.indexOf(speechModel))) return;
    if (step === "install") {
      setSaving(true);
      try { await command("complete"); } finally { setSaving(false); }
      return;
    }
    setStep(steps[steps.indexOf(step) + 1]);
  };
  const selectText = async (value: string) => {
    if (preparedProvider.current === value) return true;
    if (!await command("reset_text_choice")) return false;
    controller.setApiKey(""); controller.setEndpoint(null);
    if (!["none", "opencode"].includes(value)) {
      if (!await run("selectProvider", value)) return false;
      if (!await run("selectWorkflow", "local_asr_refinement")) return false;
    }
    preparedProvider.current = value;
    setProvider(value); setModel(""); setEndpointOpen(false);
    return true;
  };
  const connectText = async () => {
    if (pending) return;
    if (provider === "opencode") await command("connect_opencode");
    else setConnectionOpen(true);
  };
  const connectionAction = provider === "opencode"
    ? selected?.connected ? "Atualizar modelos" : selected?.runtimeInstalled ? "setup_connect_free" : "setup_install_opencode"
    : selected?.connected ? "setup_manage_connection" : "setup_connect";
  const skipText = async () => {
    if (pending) return;
    if (!await command("reset_text_choice")) return;
    controller.setApiKey(""); controller.setEndpoint(null);
    preparedProvider.current = "none";
    setProvider("none"); setModel("");
    if (await command("recommend")) setStep("speech");
  };
  const titles: Record<Step, string> = { welcome: "setup_choose_rewriting", language: "setup_choose_language", speech: "setup_speech", text: provider === "opencode" ? "setup_free_models_title" : provider === "chatgpt" ? "setup_subscription_title" : "setup_connect_plan", install: "setup_install" };
  return <main className="onboarding onboarding-page onboarding-flow personal-setup" data-step={step}>
    <div className="onboarding-content">
      <div className="setup-progress" role="progressbar" aria-label={t("setup_progress")}
        aria-valuemin={1} aria-valuemax={steps.length} aria-valuenow={steps.indexOf(step) + 1}>
        {steps.map((item, index) => <span key={item} aria-hidden="true" data-active={item === step} data-complete={index < steps.indexOf(step)} />)}
      </div>
      <div className="onboarding-heading">
        {step === "language" && <div className="setup-brand"><ClarifyLogo size={36} /><span>Clarify</span></div>}
        <h1 ref={heading} tabIndex={-1}>{t(titles[step])}</h1>
        <p className="hint">{t({ welcome: "setup_rewriting_hint", language: "setup_interface_hint", speech: "setup_speech_hint", text: provider === "opencode" ? "setup_free_models_hint" : provider === "chatgpt" ? "setup_subscription_hint" : "setup_connect_hint", install: "setup_install_hint" }[step])}</p>
      </div>
      <div className="setup-body">
        {step !== "text" && (error || setup?.error) && <p className="error setup-error" role="alert">{t(error || setup?.error || "")}</p>}
        {step === "language" && <LanguageWheel value={state.uiLanguage || "en"} disabled={pending} onChange={value => void run("personalSetupCommand", "interface_language", JSON.stringify({ interfaceLanguage: value }))} />}
        {step === "welcome" && <div className="setup-choice-list" role="radiogroup" onKeyDown={chooseRadio} aria-label={t("setup_choose_rewriting")}>
          {[
            { id: "opencode", title: "setup_free_choice", hint: "setup_free", icon: () => <ProviderBrandIcon provider="OpenCode" /> },
            { id: "chatgpt", title: "setup_subscription_choice", hint: "setup_subscription", icon: () => <ProviderBrandIcon provider="ChatGPT" /> },
            { id: "openai", title: "setup_personal_choice", hint: "setup_key_hint", icon: () => <KeyRound aria-hidden="true" size={20} /> },
            { id: "none", title: "setup_raw", hint: "setup_raw_hint", icon: () => <Mic aria-hidden="true" size={20} /> },
          ].map(({ id, title, hint, icon: Icon }) => <button key={id} type="button" role="radio" aria-checked={setupChoice === id} disabled={pending}
            className="setup-choice" onClick={() => setProvider(id === "openai" && setupChoice === "openai" ? provider : id)}><span className="setup-provider-brand"><Icon /></span><span><strong>{t(title)}</strong><small>{t(hint)}</small></span><span className="setup-radio" aria-hidden="true">{setupChoice === id && <Check size={12} />}</span></button>)}
        </div>}
        {step === "speech" && <>
          <Picker label={t("setup_languages")} value={language} options={state.languages.map(id => ({ id, label: id === "auto" ? t("setup_auto_language") : new Intl.DisplayNames([state.uiLanguage || "en"], { type: "language" }).of(id) || id }))} onChange={setLanguage} disabled={pending} />
          <div className="setup-recommendation setup-speech-card">
            <div className="setup-model-icon"><Mic aria-hidden="true" size={24} /></div>
            {speechModel === recommendation?.modelId && <span className="badge">{t("setup_recommended")}</span>}
            <h2>{t(state.localProfiles[speechIds.indexOf(speechModel)] || recommendation?.label || "")}</h2>
            <p>{t("setup_location")}</p>
            {speechModel === recommendation?.modelId && <p className="hint setup-model-download"><HardDrive aria-hidden="true" size={15} />{t("setup_download", { v0: Math.ceil((recommendation?.downloadBytes || 0) / 1024 / 1024) })}</p>}
          </div>
          {speechDescription && <p className="hint">{t(speechDescription)}</p>}
          <SettingsDisclosure title={t("setup_alternatives")} className="setup-model-options">
            <Picker label={t("setup_speech_model")} value={speechModel} options={state.localProfiles.map((label, index) => ({ id: speechIds[index], label })).filter(option => !!option.id && !["ggml-small", "ggml-medium"].includes(option.id))} disabled={pending} onChange={async id => { setSpeech(id); await run("selectLocalProfile", speechIds.indexOf(id)); }} />
            <p className="hint">{recommendation?.reason}</p>
            <p className="hint">{speechRequirements.join(" · ")}</p>
            <Button variant="text" disabled={pending} onClick={() => void command("recommend")}>{t("setup_check_again")}</Button>
          </SettingsDisclosure>
        </>}
        {step === "text" && <>
          <div className="setup-provider-section">
            <p className="setup-field-label" id="setup-provider-label">{t("setup_text_service")}</p>
            <div className="setup-provider-list" role="group" aria-labelledby="setup-provider-label">
              {(setup?.textOptions || []).filter(option => option.id === provider).map(option => <div className="setup-provider-row" key={option.id} data-selected="true">
                <div className="setup-provider-identity">
                  <span className="setup-radio" aria-hidden="true"><Check size={12} /></span>
                  <span className="setup-provider-brand" aria-hidden="true">
                    {option.id === "chatgpt" ? <ProviderBrandIcon provider="ChatGPT" /> : option.id === "opencode" ? <ProviderBrandIcon provider="OpenCode" /> : <KeyRound size={18} />}
                  </span>
                  <span><strong>{option.id === "openai" ? "OpenAI" : t(option.label)}</strong><small>{t(option.connected ? "setup_connected" : option.id === "opencode" && !option.runtimeInstalled ? "setup_runtime_needed" : "setup_not_connected")}</small></span>
                </div>
                {option.id === "opencode" && !option.runtimeInstalled && !option.connected
                  ? <Button className="setup-provider-action" disabled={pending} aria-label={t("setup_install_opencode")} onClick={() => void connectText()}>{t("setup_provider_download")}</Button>
                  : option.connected && <Button className="setup-provider-action" disabled={pending} onClick={() => void connectText()}>{t(connectionAction)}</Button>}
              </div>)}
            </div>
            {setupChoice === "openai" && <Button className="setup-more" variant="text" disabled={pending} onClick={() => { setSearch(""); setMoreOpen(true); }}><MoreHorizontal size={16} aria-hidden="true" />{t("setup_more_providers")}</Button>}
          </div>
          {setup?.busy && provider === "opencode" && <div className="setup-connection-status" role="status"><progress aria-label={t("setup_connecting")} /><span>{t("setup_connecting")}</span></div>}
          {textError && <p className="error setup-error" role="alert">{t(textError)}</p>}
          {provider !== "none" && selected?.connected && <div className="setup-provider">
            {(selected.models?.length ? <div className="setup-form-field"><p className="setup-field-label">{t("setup_rewriting_model")}</p><Picker label={t("setup_rewriting_model")} value={model || selected.modelId || ""} options={selected.models} disabled={pending} onChange={setModel} /></div> : !["chatgpt", "opencode"].includes(provider) && <Field title={t("setup_rewriting_model")} value={model || selected.modelId || ""} onChange={event => setModel(event.target.value)} />)}
          </div>}
          <Dialog open={moreOpen} onOpenChange={setMoreOpen}>
            <DialogPopup className="setup-dialog" bottomStickOnMobile={false}>
              <DialogHeader><DialogTitle>{t("setup_more_providers")}</DialogTitle><DialogDescription>{t("setup_key_hint")}</DialogDescription></DialogHeader>
              <div className="setup-dialog-body"><Input aria-label={t("setup_search_providers")} placeholder={t("setup_search_providers")} value={search} onChange={event => setSearch(event.target.value)} />
                <div className="setup-choice-list">{(setup?.textOptions || []).filter(option => ["openai", "groq", "gemini"].includes(option.id) && option.label.toLowerCase().includes(search.toLowerCase())).map(option => <Button key={option.id} variant="ghost" disabled={pending} onClick={async () => { if (await selectText(option.id)) { setMoreOpen(false); setConnectionOpen(true); } }}><KeyRound size={18} aria-hidden="true" />{option.id === "openai" ? "OpenAI" : t(option.label)}</Button>)}</div>
              </div>
            </DialogPopup>
          </Dialog>
          <Dialog open={connectionOpen} onOpenChange={setConnectionOpen}>
            <DialogPopup className="setup-dialog" bottomStickOnMobile={false}>
              <DialogHeader><DialogTitle>{provider === "openai" ? "OpenAI" : t(selected?.label || "")}</DialogTitle><DialogDescription>{t(provider === "chatgpt" ? "setup_browser_connection" : "setup_key_hint")}</DialogDescription></DialogHeader>
              <div className="setup-dialog-body setup-provider">
                {textError && <p className="error setup-error" role="alert">{t(textError)}</p>}
                {provider === "chatgpt" && <>
                  <ChatGPTPlan controller={controller} setup />
                  {selected?.connected && <Button disabled={pending} loading={controller.validatingProvider} onClick={() => void controller.validateProvider()}>{t("Atualizar modelos ChatGPT")}</Button>}
                </>}
                {!["none", "chatgpt", "opencode"].includes(provider) && <>
              {provider === "openai" && state.providerSupportsCustomEndpoint && <SettingsDisclosure title={t("setup_custom_endpoint")} className="setup-endpoint" open={endpointOpen} onOpenChange={setEndpointOpen}>
                <Field title={t("Endpoint")} value={controller.endpoint} onChange={event => controller.setEndpoint(event.target.value)} />
                <p className="hint">{t("setup_local_endpoint_hint")}</p>
              </SettingsDisclosure>}
              <Field title={t("Chave de API")} type="password" autoComplete="off" value={controller.apiKey} onChange={event => controller.setApiKey(event.target.value)} />
              <Button variant={selected?.connected ? "default" : "primary"} loading={controller.validatingProvider} disabled={pending || controller.validatingProvider} onClick={() => void controller.validateProvider()}>{t("Validar e salvar chave")}</Button>
                </>}
                {selected?.connected && <Button onClick={() => setConnectionOpen(false)}>{t("Continuar")}</Button>}
              </div>
            </DialogPopup>
          </Dialog>
        </>}
        {step === "install" && <>
          <div className="setup-recommendation"><h2>{t(state.localProfiles[speechIds.indexOf(speechModel)] || recommendation?.label || "")}</h2><p>{t("setup_location")}</p><p className="hint">{provider === "none" ? t("setup_raw") : `${selected?.label} · ${options.textModelId}`}</p></div>
          <p role="status">{t(state.localAsrDetail || (installed ? "setup_ready" : "setup_needs_install"))}</p>
          {state.localAsrBusy && <progress aria-label={t("setup_install")} max={1} value={state.localAsrProgress > 1 ? state.localAsrProgress / 100 : state.localAsrProgress} />}
          {!pending && !installed && <Button variant="primary" onClick={() => void run("installLocalAsr")}>{t(setup?.error ? "setup_retry_install" : "setup_download_install")}</Button>}
        </>}
      </div>
      <div className="onboarding-flow-actions setup-footer">
        {setup?.busy ? <Button onClick={() => state.chatgptState?.busy ? void run("chatgptCommand", "cancel", "") : void command("cancel")}>{t("Cancelar")}</Button> : step === "text" && selected && !selected.connected
          ? <Button variant="primary" disabled={pending} onClick={() => void connectText()}>{t(provider === "opencode" && !selected.runtimeInstalled ? "setup_connect" : connectionAction)}</Button>
          : (step !== "install" || installed) && (step !== "text" || textReady) && <Button variant="primary" disabled={pending || !setup} onClick={() => void next()}>{t(step === "install" ? "setup_practice" : "Continuar")}</Button>}
        {step !== "language" && <Button variant={step === "text" ? "default" : "text"} disabled={pending} onClick={() => setStep(step === "speech" && provider === "none" ? "welcome" : steps[steps.indexOf(step) - 1])}>{step !== "text" && <ArrowLeft size={16} />}{t("Voltar")}</Button>}
        {step === "text" && provider !== "none" && !setup?.busy && <Button variant="text" disabled={pending} onClick={() => void skipText()}>{t("setup_skip_text")}</Button>}
      </div>
    </div>
  </main>;
}
