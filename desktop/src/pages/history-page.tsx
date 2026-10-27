import { useEffect, useRef, useState } from "react";
import { Cloud, HardDrive, History, LoaderCircle, Monitor, Smartphone, Trash2 } from "lucide-react";
import { t, uiLanguage } from "../i18n";
import { Button, Confirm, Input } from "../components/ui";
import { HistoryComparison, HistoryEntryActions, type HistoryEntryExtension } from "../components/history-entry";
import { HistoryCorrectionAction } from "../components/history-correction-dialog";
import { getHistoryPage, type HistoryEntry } from "../settings/bridge";
import type { SettingsPageProps } from "../settings/use-settings";

export function HistoryPage({ controller, renderEntryAction }: SettingsPageProps & { renderEntryAction?: HistoryEntryExtension }) {
  const { state, run } = controller;
  const context = state.historyState?.context || "";
  const revision = state.historyState?.revision || "";
  const [deleting, setDeleting] = useState(false);
  const deletionPending = useRef(false);
  const [deletion, setDeletion] = useState<{ id: string; context: string } | null>(null);
  const [rows, setRows] = useState<HistoryEntry[]>([]);
  const [loaded, setLoaded] = useState({ context: "", revision: "", query: "" });
  const [cursor, setCursor] = useState("");
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
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
      const ok = deletion.id === "all" ? await run("clearHistory", deletion.context)
        : await run("deleteHistoryEntry", deletion.id, deletion.context);
      if (ok) setDeletion(current => current === deletion ? null : current);
    } finally {
      deletionPending.current = false;
      setDeleting(false);
    }
  };
  const Storage = state.accountState?.signedIn ? Cloud : HardDrive;
  return <div className="history-page">
    <div className="history-notice"><Storage size={16} aria-hidden="true" /><p className="hint">{t(state.accountState?.signedIn
      ? "As novas transcrições da conta são sincronizadas automaticamente. Os registros antigos permanecem neste dispositivo."
      : "Seu histórico permanece somente neste computador.")}</p></div>
    {error && <p role="alert" className="error">{t(error)}</p>}
    <form className="history-search" onSubmit={event => { event.preventDefault(); setQuery(draft.trim()); }}>
      <Input type="search" maxLength={200} value={draft} aria-label={t("Buscar no histórico")} placeholder={t("Buscar no histórico")} onChange={event => setDraft(event.target.value)} />
      <Button type="submit">{t("Buscar")}</Button>
      {query && <Button onClick={() => { setDraft(""); setQuery(""); }}>{t("Limpar busca")}</Button>}
    </form>
    <p className="hint">{t("Busca no original e no resultado, sem distinguir maiúsculas, nos registros disponíveis neste dispositivo.")}</p>
    {entries.length ? <>
      <div className="history-actions"><Button variant="text" onClick={() => setDeletion({ id: "all", context })}><Trash2 size={14} aria-hidden="true" />{t("Limpar histórico")}</Button></div>
      <div className="history-list" role="list" aria-label={t("Histórico")}>
        {entries.map(entry => {
          const Device = entry.sourceDevice === "mobile" ? Smartphone : Monitor;
          const request = generation.current, scope = Object.freeze({ context, revision }), expected = current.current;
          const isCurrent = () => active(request, expected);
          return <article className="history-row" role="listitem" key={`${context}:${revision}:${query}:${entry.id}`}>
            <div className="history-entry-content">
              <div className="history-meta">
                <time dateTime={new Date(entry.timestamp * 1000).toISOString()}>
                  {new Intl.DateTimeFormat(uiLanguage, { dateStyle: "medium", timeStyle: "short" }).format(entry.timestamp * 1000)}
                </time>
                <span><Device size={12} aria-hidden="true" />{entry.sourceDevice === "mobile" ? "Mobile" : "Desktop"}</span>
              </div>
              <p className="history-text">{entry.text || t("Sem texto")}</p>
              <HistoryEntryActions entry={entry} scope={scope} isCurrent={isCurrent}>
                <Button variant="text" aria-expanded={expanded === entry.id} onClick={() => setExpanded(value => value === entry.id ? null : entry.id)}>{t(expanded === entry.id ? "Fechar textos" : "Abrir textos")}</Button>
                {renderEntryAction ? renderEntryAction(entry, scope) : <HistoryCorrectionAction entry={entry} scope={scope} controller={controller} />}
              </HistoryEntryActions>
              {expanded === entry.id && <HistoryComparison entry={entry} scope={scope} isCurrent={isCurrent} />}
            </div>
            <Button className="history-delete" variant="text" aria-label={t("Excluir transcrição")} onClick={() => setDeletion({ id: entry.id, context })}><Trash2 size={15} aria-hidden="true" /></Button>
          </article>;
        })}
      </div>
    </> : !loading && !cursor && !error && <div className="history-empty"><History size={26} aria-hidden="true" /><p className="hint">{t(query ? "Nenhum resultado encontrado." : "Nenhuma transcrição ainda.")}</p></div>}
    {cursor && <div className="history-pagination"><Button loading={loading} onClick={() => void load(cursor)}>{t(query ? "Continuar busca" : "Carregar mais")}</Button></div>}
    {query && cursor && <p role="status" className="hint">{t("Ainda há registros para pesquisar.")}</p>}
    {error && <Button onClick={() => void load(cursor)}>{t("Tentar novamente")}</Button>}
    {loading && !entries.length && <div className="history-empty" role="status" aria-label={t("Carregando…")}><LoaderCircle size={22} className="spin" aria-hidden="true" /></div>}
    <Confirm open={deletion !== null && deletion.context === context} onOpenChange={open => { if (!open && !deletionPending.current) setDeletion(null); }}
      title={t(deletion?.id === "all" ? "Limpar histórico" : "Excluir transcrição")}
      description={t(state.accountState?.signedIn
        ? "A exclusão das transcrições da conta será sincronizada nos seus dispositivos. Os registros locais serão removidos apenas deste computador."
        : "Esta ação remove os registros deste computador.")}>
      <Button autoFocus disabled={deleting} onClick={() => setDeletion(null)}>{t("Cancelar")}</Button>
      <Button className="destructive" disabled={deleting || deletion?.context !== context} onClick={() => void confirm()}>{t("Excluir")}</Button>
    </Confirm>
  </div>;
}
