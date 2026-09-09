import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { isTauri } from "@tauri-apps/api/core";
import { AudioLines, Settings2, Mic, Sparkles, Keyboard, Cpu, Check, LoaderCircle, ArrowRight, Download, AlertCircle } from "lucide-react";
import { call, type Settings } from "./bridge";
import { Picker, Row, Toggle, Confirm } from "./ui";
import { RecordingOptions, recordingDraft, recordingValue, type RecordingDraft } from "./recording";
import "./styles.css";

const pages = [
  { id: "general", label: "Geral", icon: Settings2, description: "Idioma, inicialização e privacidade." },
  { id: "dictation", label: "Ditado", icon: Mic, description: "Microfone, modelo e revisão do texto." },
  { id: "text", label: "Texto", icon: Sparkles, description: "Modelos e instruções para transformar o texto." },
  { id: "shortcuts", label: "Atalhos", icon: Keyboard, description: "Acesse suas ações pelo teclado." },
  { id: "models", label: "Modelos e serviços", icon: Cpu, description: "Modelos locais e conexões com serviços de IA." },
];
const languageNames: Record<string, string> = { en: "English", pt: "Português", es: "Español", de: "Deutsch", ru: "Русский" };

function App() {
  const [state, setState] = useState<Settings>();
  const [page, setPage] = useState("dictation");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [navigating, setNavigating] = useState(false);
  const [saved, setSaved] = useState(false);
  const [closing, setClosing] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [prompt, setPrompt] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [capture, setCapture] = useState<string>();
  const [retention, setRetention] = useState("");
  const [recording, setRecording] = useState<RecordingDraft | null>(null);
  const [routeOverride, setRouteOverride] = useState<{ model: string; endpoint: string } | null>(null);
  const [confirmAction, setConfirmAction] = useState<"clearProvider" | "removeLocalAsr" | "resetAllHotkeys" | null>(null);
  const current = useRef(state); current.current = state;
  const pending = useRef(false);
  const localDirty = !!state && (recording !== null || routeOverride !== null || prompt !== state.routePrompt || endpoint !== state.providerBaseUrl || apiKey !== "" || retention !== String(state.historyRetentionDays ?? ""));
  const dirtyRef = useRef(false); dirtyRef.current = !!state?.dirty || !!state?.providerDirty || localDirty;
  const allowClose = useRef(false);

  const run = useCallback(async (method: string, ...args: unknown[]) => {
    pending.current = true; setBusy(true); setError(""); setSaved(false);
    try { const value = await call(method, ...args); setState(value); return value; }
    catch (e) { setError(String(e)); return false; }
    finally { pending.current = false; setBusy(false); }
  }, []);

  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      if (!pending.current && !document.hidden) {
        pending.current = true;
        try {
          let s = await call("snapshot");
          if (!current.current) {
            await call("selectWorkflow", "transcription");
            s = await call("loadRouteModels");
          }
          if (live) setState(s);
        }
        catch (e) { if (live) setError(String(e)); }
        finally { pending.current = false; }
      }
      if (live) timer = setTimeout(refresh, current.current?.microphoneTestBusy ? 100 : 1000);
    };
    const visibility = () => { if (document.hidden && current.current?.microphoneTestBusy) void call("stopMicrophoneTest"); };
    document.addEventListener("visibilitychange", visibility);
    refresh();
    return () => { live = false; clearTimeout(timer); document.removeEventListener("visibilitychange", visibility); };
  }, []);
  useEffect(() => { if (state) setRetention(String(state.historyRetentionDays ?? "")); }, [state?.historyRetentionDays]);
  useEffect(() => { if (state) setPrompt(state.routePrompt); }, [state?.routePrompt, state?.selectedScope]);
  useEffect(() => { if (state) setEndpoint(state.providerBaseUrl); }, [state?.providerBaseUrl, state?.selectedProviderId]);
  useEffect(() => {
    if (!isTauri()) return;
    const unlisten = getCurrentWindow().onCloseRequested(event => {
      if (allowClose.current) return;
      event.preventDefault(); setClosing(true);
    });
    return () => { unlisten.then(fn => fn()); };
  }, []);
  useEffect(() => {
    if (!closing || dirtyRef.current) return;
    allowClose.current = true;
    if (isTauri()) void getCurrentWindow().close();
  }, [closing]);
  const reset = async () => {
    const s = await run("load");
    if (s) { setPrompt(s.routePrompt); setEndpoint(s.providerBaseUrl); setRetention(String(s.historyRetentionDays ?? "")); setApiKey(""); setRecording(null); setRouteOverride(null); setDiscarding(false); }
    return !!s;
  };
  const save = async () => {
    if (!state || busy) return false;
    if (retention !== "" && (!/^\d+$/.test(retention) || Number(retention) > 3650)) { setError("A retenção deve ser um número inteiro entre 0 e 3650 dias."); return false; }
    if (apiKey || endpoint !== state.providerBaseUrl || state.providerDirty) { setError("Valide ou descarte as alterações do serviço antes de salvar."); return false; }
    pending.current = true; setBusy(true); setError(""); setSaved(false);
    try {
      if (recording) await call("setRecordingControls", recordingValue(recording));
      if (routeOverride) {
        await call("setRouteModelId", routeOverride.model);
        await call("setRouteCustomEndpoint", routeOverride.endpoint);
      }
      if (prompt !== state.routePrompt) await call("setRoutePrompt", prompt);
      if (retention !== String(state.historyRetentionDays ?? "")) await call("setHistoryRetentionDays", retention === "" ? null : Number(retention));
      const next = await call("save");
      setState(next); setPrompt(next.routePrompt); setSaved(true); setRecording(null); setRouteOverride(null);
      return true;
    } catch (e) { setError(String(e)); return false; }
    finally { pending.current = false; setBusy(false); }
  };
  const navigate = async (id: string, scope = id === "dictation" ? "transcription" : "refinement") => {
    if (!state || busy || (id === page && (id !== "text" || scope === state.selectedScope))) return;
    pending.current = true; setBusy(true); setNavigating(true); setError("");
    try {
      let next = state;
      if (prompt !== state.routePrompt) next = await call("setRoutePrompt", prompt);
      if (routeOverride) {
        next = await call("setRouteModelId", routeOverride.model);
        next = await call("setRouteCustomEndpoint", routeOverride.endpoint);
        setRouteOverride(null);
      }
      if (next.microphoneTestBusy) next = await call("stopMicrophoneTest");
      if (id === "dictation" || id === "text") {
        next = await call("selectWorkflow", scope);
        next = await call("loadRouteModels");
      }
      if (id === "models" && next.selectedProviderId === "local_asr") {
        const provider = next.providers.find(p => p.id !== "local_asr");
        if (provider) next = await call("selectProvider", provider.id);
      }
      // Commit the destination and its data together. Never paint the previous route.
      setState(next); setPrompt(next.routePrompt); setPage(id);
    } catch (e) { setError(String(e)); }
    finally { pending.current = false; setBusy(false); setNavigating(false); }
  };

  const route = state && <>
    <Row title="Serviço"><Picker label="Serviço" value={state.routeProviderId} options={state.routeProviders} onChange={async value => { await run("setRouteProviderId", value); await run("loadRouteModels"); }} /></Row>
    <Row title="Modelo"><Picker label="Modelo" value={state.routeModelId} options={state.routeModelOptions} onChange={value => void run("setRouteModelId", value)} onRefresh={() => void run("refreshRouteModels")} busy={state.routeModelStatus === "loading"} empty={state.routeProviderId === "local_asr" ? "Nenhum modelo instalado." : "Nenhum modelo disponível. Verifique o serviço."} /></Row>
    {["empty", "not_configured", "error"].includes(state.routeModelStatus) && <button className="text-button" onClick={() => void navigate("models")}>{state.routeModelStatus === "not_configured" ? "Conectar serviço" : "Gerenciar modelos e serviços"} <ArrowRight size={15} /></button>}
    {state.routeProviderId !== "local_asr" && <details key={state.selectedScope}><summary>Modelo e endereço personalizados</summary>
      <Row title="ID do modelo" hint="Opcional: use um modelo que não aparece no catálogo."><input className="control" aria-label="ID do modelo" value={routeOverride?.model ?? state.routeModelId} onChange={e => setRouteOverride({ model: e.target.value, endpoint: routeOverride?.endpoint ?? state.routeCustomEndpoint })} /></Row>
      <Row title="Endereço deste fluxo" hint="Deixe vazio para usar o endereço do serviço."><input className="control" aria-label="Endereço deste fluxo" value={routeOverride?.endpoint ?? state.routeCustomEndpoint} onChange={e => setRouteOverride({ endpoint: e.target.value, model: routeOverride?.model ?? state.routeModelId })} /></Row>
    </details>}
  </>;
  const info = pages.find(item => item.id === page)!;
  return <div className="app" data-navigating={navigating || undefined}>
    <aside><div className="brand"><AudioLines size={23} strokeWidth={1.6} /><span>Clarify</span></div>
      <span className="nav-heading">CONFIGURAÇÕES</span>
      <nav aria-label="Configurações">{pages.map(({ id, label, icon: Icon }) => <button key={id} disabled={busy} aria-label={label} aria-current={id === page ? "page" : undefined} onClick={() => void navigate(id)}><Icon size={18} strokeWidth={1.6} /><span>{label}</span></button>)}</nav>
    </aside>
    <main><header><h1>{info.label}</h1><p>{info.description}</p></header>
      <div className="scroll-area"><div className="page">
      {!state ? <div className="connection" role="status"><LoaderCircle className="spin" size={22} />Conectando ao Clarify…</div> : <fieldset disabled={busy}>
        {page === "general" && <>
          <section><h2>Preferências</h2><Row title="Idioma do texto"><Picker label="Idioma" value={state.language} options={state.languages.map(id => ({ id, label: languageNames[id] || id }))} onChange={v => void run("setLanguage", v)} /></Row>
            <Toggle title="Iniciar com o Windows" hint="Deixe o Clarify pronto quando você precisar." checked={state.autostart} onChange={v => void run("setAutostart", v)} /></section>
          <section><h2>Privacidade</h2><Toggle title="Salvar histórico" hint="Mantenha suas transcrições neste computador." checked={state.historyEnabled} onChange={v => void run("setHistoryEnabled", v)} />
            {state.historyEnabled && <Row title="Retenção do histórico" hint="Em dias. Deixe vazio para não definir um prazo."><input aria-label="Retenção do histórico" className="control" type="number" min="0" max="3650" value={retention} onChange={e => setRetention(e.target.value)} /></Row>}</section>
        </>}
        {page === "dictation" && <>
          <section><h2>Entrada de áudio</h2><Row title="Microfone"><Picker label="Microfone" value={state.selectedMicrophoneId || ""} options={state.microphoneDevices.map(device => device.id ? device : { ...device, label: "Padrão do sistema" })} onChange={v => void run("selectMicrophone", v)} onRefresh={() => void run("refreshMicrophones")} /></Row>
            <div className="mic-test"><div className="wave" aria-label="Nível do microfone">{Array.from({ length: 36 }, (_, i) => <i key={i} style={{ height: `${3 + (state.microphoneTestBusy ? state.microphoneTestLevel * (10 + 25 * Math.abs(Math.sin(i * 1.9))) : 0)}px` }} />)}</div>
              <button className="button" onClick={() => void run(state.microphoneTestBusy ? "stopMicrophoneTest" : "testMicrophone")}>{state.microphoneTestBusy ? "Parar teste" : "Testar microfone"}</button></div>
            {state.microphoneTestStatus && <p className="hint" role="status">{state.microphoneTestStatus === "Test stopped." ? "Teste encerrado." : state.microphoneTestStatus}</p>}</section>
          <section><h2>Transcrição</h2>{route}<Toggle title="Ativar ditado" checked={state.routeEnabled} onChange={v => void run("setRouteEnabled", v)} />
            <details><summary>Instruções da transcrição</summary><textarea className="control prompt" aria-label="Instruções da transcrição" value={prompt} onChange={e => setPrompt(e.target.value)} /></details>
          </section>
          <section><RecordingOptions value={recording ?? recordingDraft(state.recordingControls)} onChange={setRecording} /></section>
          {state.routeProviderId === "local_asr" && <section><h2>Acabamento do texto</h2><Toggle title="Revisar com IA na nuvem" hint="Após a transcrição local, envie o texto ao serviço de revisão configurado." checked={state.localAsrCloudRefinement} onChange={v => void run("setLocalAsrCloudRefinement", v)} /></section>}
        </>}
        {page === "text" && <>
          <div className="segmented" aria-label="Fluxo de texto">{[{ id: "refinement", label: "Revisão" }, { id: "rewrite", label: "Reescrita" }, { id: "translation", label: "Tradução" }].map(item => <button key={item.id} aria-pressed={state.selectedScope === item.id || (item.id === "refinement" && state.selectedScope === "local_asr_refinement")} onClick={() => void navigate("text", item.id)}>{item.label}</button>)}</div>
          {(state.selectedScope === "refinement" || state.selectedScope === "local_asr_refinement") && <Row title="Revisar transcrições de"><Picker label="Contexto da revisão" value={state.selectedScope} options={[{ id: "refinement", label: "Ditado na nuvem" }, { id: "local_asr_refinement", label: "Transcrição local" }]} onChange={v => void navigate("text", v)} /></Row>}
          <section>{route}<Toggle title="Ativar este fluxo" checked={state.routeEnabled && (state.selectedScope !== "local_asr_refinement" || state.localAsrCloudRefinement)} onChange={async v => { if (state.selectedScope === "local_asr_refinement" && !await run("setLocalAsrCloudRefinement", v)) return; await run("setRouteEnabled", v); }} /></section>
          <section><h2>Instruções</h2><p className="hint">Defina o tom e as alterações que a IA deve aplicar.</p><textarea className="control prompt" aria-label="Instruções" value={prompt} onChange={e => setPrompt(e.target.value)} placeholder="Como o texto deve ser revisado?" /></section>
        </>}
        {page === "shortcuts" && <section><h2>Ações rápidas</h2>
          {state.hotkeyActions.map(item => <Row key={item.id} title={item.label}><div className="inline-actions"><button className="control shortcut" onClick={() => setCapture(item.id)}> {item.display || item.definition?.display || "Definir atalho"} </button><button className="button ghost" aria-label={`Restaurar ${item.label}`} onClick={() => void run("resetHotkey", item.id)}>Restaurar</button></div></Row>)}
          <button className="text-button" onClick={() => setConfirmAction("resetAllHotkeys")}>Restaurar todos os atalhos</button>
          <Row title="Modo de gravação"><Picker label="Modo de gravação" value={state.hotkeyActivationMode} options={[{ id: "toggle", label: "Pressionar para iniciar e parar" }, ...(state.hotkeyPushToTalkSupported ? [{ id: "push_to_talk", label: "Segurar para gravar" }] : [])]} onChange={v => void run("setHotkeyActivationMode", v)} /></Row>
        </section>}
        {page === "models" && <>
          <section><h2>Modelos locais <span className="badge">No seu computador</span></h2><p className="hint">Transcreva sem enviar o áudio para um serviço externo.</p>
            <Row title="Modelo"><Picker label="Modelo local" disabled={state.localAsrBusy || state.localBenchmarkBusy} value={String(state.localProfileIndex)} options={state.localProfiles.map((label, i) => ({ id: String(i), label }))} onChange={v => void run("selectLocalProfile", Number(v))} /></Row>
            <Row title="Processamento"><Picker label="Processamento" disabled={state.localAsrBusy || state.localBenchmarkBusy} value={String(state.localDeviceIndex)} options={state.localDevices.map((label, i) => ({ id: String(i), label }))} onChange={v => void run("selectLocalDevice", Number(v))} /></Row>
            <div className="installation"><div><div className="installation-status">{state.localAsrStatus === "installed" ? <><Check size={17} /> Pronto para usar</> : state.localAsrBusy ? <><LoaderCircle size={17} className="spin" /> Preparando modelo…</> : "Instalação do modelo"}</div><p className="hint">{state.localAsrDetail}</p></div>
              {state.localAsrBusy ? <button className="button" onClick={() => void run("cancelLocalAsr")}>Cancelar</button> : state.localAsrStatus !== "installed" && state.localAsrCanInstall ? <button className="button" onClick={() => void run("installLocalAsr")}><Download size={16} />Instalar</button> : <button className="button" onClick={() => void run("refreshLocalAsr")}>Verificar</button>}</div>
            {state.localAsrBusy && <progress aria-label="Instalação do modelo" max="1" value={state.localAsrProgress >= 0 ? state.localAsrProgress : undefined} />}
            {state.localAsrRequirementsList.length > 0 && <details><summary>Requisitos do modelo</summary><ul>{state.localAsrRequirementsList.map(value => <li key={value}>{value}</li>)}</ul></details>}
            <details><summary>Opções do modelo local</summary>
              <Toggle title="Processar pausas durante a gravação" hint="Experimental. Usa o modelo local enquanto você fala." checked={state.localStreaming} onChange={v => void run("setLocalStreaming", v)} />
              <p className="hint" role="status">{state.localBenchmarkDetail}</p>
              <div className="inline-actions">
                <button className="button" disabled={state.localAsrBusy} onClick={() => void run(state.localBenchmarkBusy ? "cancelLocalMeasurement" : "installLocalAsr")}>{state.localBenchmarkBusy ? "Cancelar medição" : "Otimizar CPU/GPU"}</button>
                {state.localAsrStatus === "installed" && <><button className="button" disabled={state.localAsrBusy || state.localBenchmarkBusy} onClick={async () => { if (await run("useLocalAsr")) await navigate("dictation"); }}>Usar este modelo</button><button className="button ghost" disabled={state.localAsrBusy || state.localBenchmarkBusy} onClick={() => setConfirmAction("removeLocalAsr")}>Remover modelo</button></>}
              </div>
            </details>
          </section>
          <section><h2>Serviços na nuvem <span className="badge">Sua chave de API</span></h2><Row title="Serviço"><Picker label="Serviço na nuvem" value={state.selectedProviderId} options={state.providers.filter(p => p.id !== "local_asr")} onChange={async v => { if (apiKey || state.providerDirty || endpoint !== state.providerBaseUrl) { setError("Valide ou descarte as alterações antes de trocar de serviço."); return; } await run("selectProvider", v); }} /></Row>
            {state.selectedProviderId !== "local_asr" && <><Row title="Chave de API" hint={state.providerHasApiKey ? "Uma chave já está salva. Preencha apenas para substituí-la." : "A chave fica no armazenamento seguro do Clarify."}><input className="control" type="password" aria-label="Chave de API" autoComplete="off" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder={state.providerHasApiKey ? "••••••••••••••••" : "Cole sua chave"} /></Row>
              {state.providerSupportsCustomEndpoint && <details><summary>Endereço personalizado</summary><input className="control" aria-label="Endpoint" value={endpoint} onChange={e => setEndpoint(e.target.value)} /></details>}
              <div className="service-actions"><span className="hint" role="status">{state.providerError || (state.providerHasApiKey ? "Chave configurada" : "Sem chave configurada")}</span><button className="button" disabled={state.providerBusy || busy} onClick={async () => { if (apiKey && !await run("setProviderApiKey", apiKey)) return; if (endpoint !== state.providerBaseUrl && !await run("setProviderBaseUrl", endpoint)) return; if (await run("validateProvider")) setApiKey(""); }}>{state.providerBusy ? "Validando…" : "Validar e salvar chave"}</button></div>
              {state.providerHasApiKey && <button className="text-button" disabled={state.providerBusy} onClick={() => setConfirmAction("clearProvider")}>Remover chave salva</button>}
            </>}
          </section>
        </>}
      </fieldset>}
      </div></div>
      <footer>{error ? <div role="alert" className="error"><AlertCircle size={17} /><span>{error}</span></div> : <span className="save-status" role="status">{saved ? <><Check size={16} />Alterações salvas</> : state?.dirty || localDirty || state?.providerDirty ? "Alterações não salvas" : "Tudo em dia"}</span>}
        <div className="footer-actions"><button className="button ghost" disabled={busy || !dirtyRef.current} onClick={() => setDiscarding(true)}>Descartar</button><button className="button primary" disabled={busy || !dirtyRef.current || !state} onClick={() => void save()}>{busy && !navigating ? <LoaderCircle size={15} className="spin" /> : null}Salvar alterações</button></div>
      </footer>
    </main>
    <Confirm open={confirmAction !== null} onOpenChange={v => { if (!v) setConfirmAction(null); }} title={confirmAction === "clearProvider" ? "Remover chave salva?" : confirmAction === "removeLocalAsr" ? "Remover modelo local?" : "Restaurar atalhos?"} description={confirmAction === "clearProvider" ? "A chave será removida do armazenamento seguro agora. Será necessário adicioná-la novamente para usar este serviço." : confirmAction === "removeLocalAsr" ? "Os arquivos deste modelo serão removidos agora. Para usá-lo novamente, será necessário reinstalá-lo." : "Os atalhos voltarão ao padrão. Use Salvar alterações para aplicar ou Descartar para manter os atalhos atuais."}>
      <button className="button ghost" disabled={busy} onClick={() => setConfirmAction(null)}>Cancelar</button>
      <button className="button" disabled={busy} onClick={async () => { if (confirmAction && await run(confirmAction)) { if (confirmAction === "clearProvider") setApiKey(""); setConfirmAction(null); } }}>Confirmar</button>
    </Confirm>
    <Confirm open={closing && dirtyRef.current || discarding} onOpenChange={value => { if (!value) { setClosing(false); setDiscarding(false); } }} title="Alterações não salvas" description="Salve suas alterações ou descarte-as para continuar.">
      <button className="button ghost" onClick={() => { setClosing(false); setDiscarding(false); }}>Continuar editando</button>
      <button className="button" onClick={async () => { if (await reset()) { if (closing && isTauri()) { allowClose.current = true; await getCurrentWindow().close(); } setClosing(false); } }}>Descartar</button>
      <button className="button primary" onClick={async () => { if (await save()) { if (closing && isTauri()) { allowClose.current = true; await getCurrentWindow().close(); } setClosing(false); setDiscarding(false); } }}>Salvar</button>
    </Confirm>
    <Confirm open={!!capture} onOpenChange={v => { if (!v) setCapture(undefined); }} title="Definir atalho" description="Clique no campo e pressione a combinação desejada.">
      <input className="control" aria-label="Novo atalho" placeholder="Pressione as teclas…" autoFocus readOnly onKeyDown={async e => {
        if (e.key === "Escape") return;
        e.preventDefault(); if (["Control", "Alt", "Shift", "Meta"].includes(e.key) || e.repeat) return;
        const modifiers = [...(e.ctrlKey ? ["ctrl"] : []), ...(e.altKey ? ["alt"] : []), ...(e.shiftKey ? ["shift"] : []), ...(e.metaKey ? ["win"] : [])];
        if (await run("setHotkey", capture, { modifiers, key: e.key === " " ? "SPACE" : e.key.toUpperCase() })) setCapture(undefined);
      }} />
    </Confirm>
  </div>;
}

createRoot(document.getElementById("root")!).render(<App />);
