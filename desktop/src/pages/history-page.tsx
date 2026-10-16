import { useEffect, useRef, useState } from "react";
import { LoaderCircle, Monitor, Smartphone, Trash2 } from "lucide-react";
import { t, uiLanguage } from "../i18n";
import { Button, Confirm } from "../components/ui";
import { getHistoryPage, getHistoryTextPart, type HistoryEntry } from "../settings/bridge";
import type { SettingsPageProps } from "../settings/use-settings";

export function HistoryPage({ controller }: SettingsPageProps) {
  const { state, run, busy } = controller;
  const context = state.historyState?.context || "";
  const revision = state.historyState?.revision || "";
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
    if (!deletion || deletion.context !== context) return;
    const ok = deletion.id === "all" ? await run("clearHistory", deletion.context)
      : await run("deleteHistoryEntry", deletion.id, deletion.context);
    if (ok) setDeletion(null);
  };
  return <>
    <p className="hint">{t(state.accountState?.signedIn
      ? "As novas transcrições da conta são sincronizadas automaticamente. Os registros antigos permanecem neste dispositivo."
      : "Seu histórico permanece somente neste computador.")}</p>
    {error && <p role="alert" className="error">{t(error)}</p>}
    {entries.length ? <>
      <div className="history-actions"><Button variant="text" onClick={() => setDeletion({ id: "all", context })}>{t("Limpar histórico")}</Button></div>
      <div className="history-list" role="list" aria-label={t("Histórico")}>
        {entries.map(entry => {
          const Device = entry.sourceDevice === "mobile" ? Smartphone : Monitor;
          return <article className="history-row" role="listitem" key={entry.id}>
            <div className="history-meta">
              <time dateTime={new Date(entry.timestamp * 1000).toISOString()}>
                {new Intl.DateTimeFormat(uiLanguage, { dateStyle: "medium", timeStyle: "short" }).format(entry.timestamp * 1000)}
              </time>
              <span><Device size={12} aria-hidden="true" />{entry.sourceDevice === "mobile" ? "Mobile" : "Desktop"}</span>
            </div>
            <div><p className="history-text">{entry.text || t("Sem texto")}</p>
              {entry.truncated && <Button variant="text" loading={expanding === entry.id} onClick={() => void expand(entry)}>{t("Mostrar texto completo")}</Button>}
            </div>
            <Button variant="text" aria-label={t("Excluir transcrição")} onClick={() => setDeletion({ id: entry.id, context })}><Trash2 size={16} /></Button>
          </article>;
        })}
      </div>
      {cursor && <Button loading={loading} onClick={() => void load(cursor)}>{t("Carregar mais")}</Button>}
    </> : !loading && <p className="hint">{t("Nenhuma transcrição ainda.")}</p>}
    {loading && !entries.length && <span role="status" aria-label={t("Carregando…")}><LoaderCircle size={20} className="spin" /></span>}
    <Confirm open={deletion !== null && deletion.context === context} onOpenChange={open => { if (!open) setDeletion(null); }}
      title={t(deletion?.id === "all" ? "Limpar histórico" : "Excluir transcrição")}
      description={t(state.accountState?.signedIn
        ? "A exclusão das transcrições da conta será sincronizada nos seus dispositivos. Os registros locais serão removidos apenas deste computador."
        : "Esta ação remove os registros deste computador.")}>
      <Button autoFocus disabled={busy} onClick={() => setDeletion(null)}>{t("Cancelar")}</Button>
      <Button className="destructive" disabled={busy || deletion?.context !== context} onClick={() => void confirm()}>{t("Excluir")}</Button>
    </Confirm>
  </>;
}
