import { useCallback, useEffect, useId, useRef, useState } from "react";
import { History, LoaderCircle, Monitor, Smartphone } from "lucide-react";
import { t, uiLanguage } from "../i18n";
import { calendarDay, historyDayTitle } from "../../../shared/history";
import { Collapsible, CollapsibleTrigger } from "../components/primitives/collapsible";
import { Button, Confirm } from "../components/ui";
import { HistoryAudioActions } from "../components/history-audio-actions";
import { HistoryComparison, HistoryDetailsPanel, HistoryEntryActions, type HistoryEntryExtension } from "../components/history-entry";
import { PageSearch } from "../components/page-search";
import { HistoryCorrectionAction } from "../components/history-correction-dialog";
import { recordingRecovery, type RecoveryRecording, getHistoryPage, type HistoryEntry } from "../settings/bridge";
import type { SettingsPageProps } from "../settings/use-settings";

export function HistoryPage({ controller, renderEntryAction }: SettingsPageProps & { renderEntryAction?: HistoryEntryExtension }) {
  const { state, run } = controller;
  const [recordings, setRecordings] = useState<RecoveryRecording[]>([]);
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const [recoveryError, setRecoveryError] = useState("");
  const [recoveryMessage, setRecoveryMessage] = useState("");
  const [deletingRecording, setDeletingRecording] = useState<string | null>(null);
  const recoveryPending = useRef(false);
  const recover = async (action: "list" | "delete" | "reprocess" | "undo", token = "") => {
    if (action !== "list" && recoveryPending.current) return;
    if (action !== "list") { recoveryPending.current = true; setRecoveryBusy(true); }
    setRecoveryError("");
    setRecoveryMessage("");
    try {
      const result = await recordingRecovery(action, token);
      if (result.entries) setRecordings(result.entries);
      if (result.started) setRecoveryMessage(t("Reprocessamento iniciado. O resultado será exibido no aplicativo."));
      if (action === "delete") setDeletingRecording(null);
    } catch {
      setRecoveryError(t("Não foi possível acessar a gravação. Aguarde o processamento atual e tente novamente."));
    } finally {
      if (action !== "list") { recoveryPending.current = false; setRecoveryBusy(false); }
    }
  };
  useEffect(() => { void recover("list"); }, [state.recordingRevision, state.historyState?.context, state.historyState?.revision]);
  const headingId = useId();
  const searchScope = useRef<HTMLDivElement>(null);
  const context = state.historyState?.context || "";
  const revision = state.historyState?.revision || "";
  const [deleting, setDeleting] = useState(false);
  const deletionPending = useRef(false);
  const [deletion, setDeletion] = useState<{ id: string; context: string } | null>(null);
  const [rows, setRows] = useState<HistoryEntry[]>([]);
  const [today, setToday] = useState(() => new Date());
  useEffect(() => {
    const next = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1);
    const timer = window.setTimeout(() => setToday(new Date()), Math.max(0, next.getTime() - Date.now()));
    return () => window.clearTimeout(timer);
  }, [today]);
  const [loaded, setLoaded] = useState({ context: "", revision: "", query: "" });
  const [cursor, setCursor] = useState("");
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const changeSearch = useCallback((value: string) => {
    setDraft(value);
    if (!value.trim()) setQuery("");
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(draft.trim()), 200);
    return () => window.clearTimeout(timer);
  }, [draft]);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const current = useRef({ context, revision, query });
  current.current = { context, revision, query };
  const entries = loaded.context === context && loaded.revision === revision && loaded.query === query ? rows : [];
  const active = (request: number, expected = current.current) => generation.current === request && expected.context === current.current.context && expected.revision === current.current.revision && expected.query === current.current.query;
  const load = async (nextCursor: string, expected = current.current, request = generation.current) => {
    setLoading(true);
    try {
      const page = await getHistoryPage(expected.context, nextCursor, expected.query);
      if (!active(request, expected) || page.context !== current.current.context || page.revision !== current.current.revision) return;
      setRows(previous => nextCursor ? [...previous, ...page.entries.filter(item => !previous.some(old => old.id === item.id))] : page.entries);
      setLoaded({ context: page.context, revision: page.revision, query: expected.query });
      setCursor(page.cursor);
      setError("");
    } catch (problem) {
      if (active(request, expected)) setError(String(problem));
    } finally {
      if (active(request, expected)) setLoading(false);
    }
  };
  useEffect(() => {
    const request = ++generation.current;
    setDeletion(null);
    setRows([]);
    setCursor("");
    setExpanded(null);
    setError("");
    void load("", { context, revision, query }, request);
    return () => { generation.current++; };
  }, [context, revision, query]);
  const confirm = async () => {
    if (!deletion || deletion.context !== context || deletionPending.current) return;
    deletionPending.current = true;
    setDeleting(true);
    try {
      const ok = await run("deleteHistoryEntry", deletion.id, deletion.context);
      if (ok) setDeletion(current => current === deletion ? null : current);
    } finally {
      deletionPending.current = false;
      setDeleting(false);
    }
  };
  type Item = { kind: "text"; entry: HistoryEntry; timestamp: number } | { kind: "audio"; recording: RecoveryRecording; timestamp: number };
  const items: Item[] = [...entries.map(entry => ({ kind: "text" as const, entry, timestamp: entry.timestamp })),
    ...(!query ? recordings.map(recording => ({ kind: "audio" as const, recording, timestamp: recording.timestamp })) : [])];
  items.sort((a, b) => b.timestamp - a.timestamp);
  const days = new Map<string, { label: string; items: Item[] }>();
  for (const item of items) {
    const date = new Date(item.timestamp * 1000);
    const key = calendarDay(date);
    const group = days.get(key);
    if (group) group.items.push(item);
    else days.set(key, { label: historyDayTitle(date, today, uiLanguage, t("Hoje")), items: [item] });
  }
  const firstDay = days.values().next().value;
  return <div className="history-page" ref={searchScope}>
    <div className="history-heading">
      <h3 className="history-date" id={headingId}>{firstDay?.label || t("Histórico")}</h3>
      <PageSearch label={t("Buscar no histórico")} query={draft} onQueryChange={changeSearch} maxLength={200} interactionBoundary={searchScope} />
    </div>
    {recoveryError && <p role="alert" className="error">{recoveryError}</p>}
    {recoveryMessage && <p role="status" className="hint">{recoveryMessage}</p>}
    {error && <p role="alert" className="error">{t(error)}</p>}
    {items.length ? <>
      <div className="history-days" role="group" aria-label={t("Histórico")}>
        {[...days].map(([day, group], index) => <section className="history-day" key={day} aria-labelledby={index === 0 ? headingId : undefined}>
          {index > 0 && <h3 className="history-date">{group.label}</h3>}
          <div className="history-list" role="list" aria-label={group.label}>
            {group.items.map(item => {
              if (item.kind === "audio") {
                const recording = item.recording;
                return <div role="listitem" key={`audio:${recording.id}`}>
                  <article className="history-row history-with-audio">
                    <div className="history-entry-content">
                      <div className="history-meta"><time dateTime={new Date(recording.timestamp * 1000).toISOString()}>{new Intl.DateTimeFormat(uiLanguage, { timeStyle: "short" }).format(recording.timestamp * 1000)}</time><span className="history-device"><Monitor size={12} aria-hidden="true" /> Desktop</span></div>
                      <div className="history-summary"><span className="history-text history-audio-summary">{t(recording.status === "processing" ? "Processando áudio…" : recording.status === "complete" ? "Áudio salvo" : "Áudio não processado")}</span></div>
                      <div className="history-row-tools"><HistoryAudioActions recording={recording} busy={recoveryBusy} onRetry={() => void recover("reprocess", recording.id)} onUndo={() => {}} onDelete={() => setDeletingRecording(recording.id)} /></div>
                    </div>
                  </article>
                </div>;
              }
              const entry = item.entry;
              const Device = entry.sourceDevice === "mobile" ? Smartphone : Monitor;
              const request = generation.current, scope = Object.freeze({ context, revision }), expected = current.current;
              const isCurrent = () => active(request, expected);
              return <div role="listitem" key={`${context}:${revision}:${query}:${entry.id}`}>
                <Collapsible className={entry.recording ? "history-row history-with-audio" : "history-row"} render={<article />} open={expanded === entry.id} onOpenChange={open => setExpanded(open ? entry.id : null)}>
                  <div className="history-entry-content">
                    <div className="history-meta">
                      <time dateTime={new Date(entry.timestamp * 1000).toISOString()}>
                        {new Intl.DateTimeFormat(uiLanguage, { timeStyle: "short" }).format(entry.timestamp * 1000)}
                      </time>
                      <span className="history-device"><Device size={12} aria-hidden="true" /> {entry.sourceDevice === "mobile" ? "Mobile" : "Desktop"}</span>
                    </div>
                    <CollapsibleTrigger className="history-summary" aria-describedby={`history-preview-${entry.id}`} aria-label={t(expanded === entry.id ? "Fechar textos" : "Abrir textos")}><span id={`history-preview-${entry.id}`} className="history-text">{entry.text || t("Sem texto")}</span></CollapsibleTrigger>
                    <HistoryEntryActions entry={entry} scope={scope} isCurrent={isCurrent} onDelete={() => setDeletion({ id: entry.id, context })} busy={recoveryBusy} onRetry={() => { if (entry.recording) void recover("reprocess", entry.recording.id); }} onUndo={() => { if (entry.recording) void recover("undo", entry.recording.id); }} />
                    <HistoryDetailsPanel>
                      <HistoryComparison entry={entry} scope={scope} isCurrent={isCurrent} />
                      <div className="history-detail-footer">{renderEntryAction ? renderEntryAction(entry, scope) : <HistoryCorrectionAction entry={entry} scope={scope} controller={controller} />}</div>
                    </HistoryDetailsPanel>
                  </div>
              </Collapsible></div>;
            })}
          </div>
        </section>)}
      </div>
    </> : !loading && !cursor && !error && <div className="history-empty"><History size={26} aria-hidden="true" /><p className="hint">{t(query ? "Nenhum resultado encontrado." : "Nenhuma transcrição ainda.")}</p></div>}
    {cursor && <div className="history-pagination"><Button loading={loading} onClick={() => void load(cursor)}>{t(query ? "Continuar busca" : "Carregar mais")}</Button></div>}
    {query && cursor && <p role="status" className="hint">{t("Ainda há registros para pesquisar.")}</p>}
    {error && <Button onClick={() => void load(cursor)}>{t("Tentar novamente")}</Button>}
    {loading && !entries.length && <div className="history-empty" role="status" aria-label={t("Carregando…")}><LoaderCircle size={22} className="spin" aria-hidden="true" /></div>}
    <Confirm open={deletion !== null && deletion.context === context} onOpenChange={open => { if (!open && !deletionPending.current) setDeletion(null); }}
      title={t("Excluir transcrição")}
      description={t(state.accountState?.signedIn
        ? "A exclusão das transcrições da conta será sincronizada nos seus dispositivos. Os registros locais serão removidos apenas deste computador."
        : "Esta ação remove os registros deste computador.") + (entries.find(entry => entry.id === deletion?.id)?.recording ? " " + t("O áudio salvo neste dispositivo também será excluído.") : "")}>
      <Button autoFocus disabled={deleting} onClick={() => setDeletion(null)}>{t("Cancelar")}</Button>
      <Button variant="destructive" disabled={deleting || deletion?.context !== context} onClick={() => void confirm()}>{t("Excluir")}</Button>
    </Confirm>
    <Confirm open={deletingRecording !== null} onOpenChange={open => { if (!open && !recoveryBusy) setDeletingRecording(null); }} title={t("Excluir gravação")} description={t("Esta ação remove o áudio salvo deste computador.")}>
      <Button disabled={recoveryBusy} onClick={() => setDeletingRecording(null)}>{t("Cancelar")}</Button>
      <Button variant="destructive" disabled={recoveryBusy} onClick={() => { if (deletingRecording) void recover("delete", deletingRecording); }}>{t("Excluir")}</Button>
    </Confirm>
  </div>;
}
