import { useEffect, useRef, useState } from "react";
import { Cloud, HardDrive, History, LoaderCircle, Monitor, Smartphone, Trash2 } from "lucide-react";
import { t, uiLanguage } from "../i18n";
import { Button, Confirm } from "../components/ui";
import { getHistoryPage, getHistoryTextPart, type HistoryEntry } from "../settings/bridge";
import type { SettingsPageProps } from "../settings/use-settings";

export function HistoryPage({ controller }: SettingsPageProps) {
  const { state, run } = controller;
  const context = state.historyState?.context || "";
  const revision = state.historyState?.revision || "";
  const [deleting, setDeleting] = useState(false);
  const deletionPending = useRef(false);
  const [deletion, setDeletion] = useState<{ id: string; context: string } | null>(null);
  const [rows, setRows] = useState<HistoryEntry[]>([]);
  const [loaded, setLoaded] = useState({ context: "", revision: "" });
  const [cursor, setCursor] = useState("");
  const [loading, setLoading] = useState(false);
  const [expanding, setExpanding] = useState<string | null>(null);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const current = useRef({ context, revision });
  current.current = { context, revision };
  const entries = loaded.context === context && loaded.revision === revision ? rows : [];
  const load = async (nextCursor: string, expected = current.current, request = generation.current) => {
    setLoading(true);
    try {
      const page = await getHistoryPage(expected.context, nextCursor);
      if (generation.current !== request || page.context !== current.current.context || page.revision !== current.current.revision) return;
      setRows(previous => nextCursor ? [...previous, ...page.entries.filter(item => !previous.some(old => old.id === item.id))] : page.entries);
      setLoaded({ context: page.context, revision: page.revision });
      setCursor(page.cursor);
      setError("");
    } catch (problem) {
      if (generation.current === request) setError(String(problem));
    } finally {
      if (generation.current === request) setLoading(false);
    }
  };
  useEffect(() => {
    const request = ++generation.current;
    setDeletion(null);
    setRows([]);
    setCursor("");
    setExpanding(null);
    setError("");
    void load("", { context, revision }, request);
    return () => { generation.current++; };
  }, [context, revision]);
  const expand = async (entry: HistoryEntry) => {
    const request = generation.current;
    const expected = current.current;
    setExpanding(entry.id);
    try {
      let offset = 0, text = "", more = true;
      while (more) {
        const part = await getHistoryTextPart(expected.context, entry.id, offset);
        if (request !== generation.current || part.context !== current.current.context) return;
        text += part.text;
        offset = part.nextOffset;
        more = part.hasMore;
      }
      if (request === generation.current) setRows(previous => previous.map(row => row.id === entry.id ? { ...row, text, truncated: false } : row));
    } catch (problem) {
      if (request === generation.current) setError(String(problem));
    } finally {
      if (request === generation.current) setExpanding(null);
    }
  };
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
    {entries.length ? <>
      <div className="history-actions"><Button variant="text" onClick={() => setDeletion({ id: "all", context })}><Trash2 size={14} aria-hidden="true" />{t("Limpar histórico")}</Button></div>
      <div className="history-list" role="list" aria-label={t("Histórico")}>
        {entries.map(entry => {
          const Device = entry.sourceDevice === "mobile" ? Smartphone : Monitor;
          return <article className="history-row" role="listitem" key={entry.id}>
            <div className="history-entry-content">
              <div className="history-meta">
                <time dateTime={new Date(entry.timestamp * 1000).toISOString()}>
                  {new Intl.DateTimeFormat(uiLanguage, { dateStyle: "medium", timeStyle: "short" }).format(entry.timestamp * 1000)}
                </time>
                <span><Device size={12} aria-hidden="true" />{entry.sourceDevice === "mobile" ? "Mobile" : "Desktop"}</span>
              </div>
              <p className="history-text">{entry.text || t("Sem texto")}</p>
              {entry.truncated && <Button className="history-expand" variant="text" loading={expanding === entry.id} onClick={() => void expand(entry)}>{t("Mostrar texto completo")}</Button>}
            </div>
            <Button className="history-delete" variant="text" aria-label={t("Excluir transcrição")} onClick={() => setDeletion({ id: entry.id, context })}><Trash2 size={15} aria-hidden="true" /></Button>
          </article>;
        })}
      </div>
      {cursor && <div className="history-pagination"><Button loading={loading} onClick={() => void load(cursor)}>{t("Carregar mais")}</Button></div>}
    </> : !loading && <div className="history-empty"><History size={26} aria-hidden="true" /><p className="hint">{t("Nenhuma transcrição ainda.")}</p></div>}
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
