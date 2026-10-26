import { useEffect, useRef, useState, type ReactNode } from "react";
import { Copy } from "lucide-react";
import { t } from "../i18n";
import { Button } from "./ui";
import { copyHistoryText, getHistoryTextPart, type HistoryEntry, type HistoryScope, type HistoryTextField } from "../settings/bridge";

export type HistoryEntryExtension = (entry: HistoryEntry, scope: HistoryScope) => ReactNode;

export function HistoryEntryActions({ entry, scope, isCurrent, children }: {
  entry: HistoryEntry; scope: HistoryScope; isCurrent: () => boolean; children?: ReactNode;
}) {
  const [copying, setCopying] = useState<HistoryTextField | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const pending = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const active = () => mounted.current && isCurrent();
  const copy = async (field: HistoryTextField) => {
    if (pending.current || !active()) return;
    pending.current = true;
    setCopying(field); setNotice(""); setError("");
    try {
      const result = await copyHistoryText(scope, entry.id, field, active);
      if (active() && result?.context === scope.context && result.revision === scope.revision && result.id === entry.id) setNotice(t("Copiado."));
    } catch (problem) {
      if (active()) setError(t(String(problem)));
    } finally {
      pending.current = false;
      if (active()) setCopying(null);
    }
  };
  return <>
    <div className="history-entry-actions">
      <Button variant="text" disabled={copying !== null} loading={copying === "text"} onClick={() => void copy("text")}><Copy size={14} aria-hidden="true" />{t("Copiar resultado")}</Button>
      {entry.hasOriginal && <Button variant="text" disabled={copying !== null} loading={copying === "transcript"} onClick={() => void copy("transcript")}>{t("Copiar original")}</Button>}
      {children}
    </div>
    {notice && <p role="status" className="hint">{notice}</p>}
    {error && <p role="alert" className="error">{error}</p>}
  </>;
}

function HistoryTextReader({ scope, id, field, isCurrent }: {
  scope: HistoryScope; id: string; field: HistoryTextField; isCurrent: () => boolean;
}) {
  const [offset, setOffset] = useState(0);
  const [part, setPart] = useState<{ text: string; nextOffset: number; hasMore: boolean } | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setPart(null); setError("");
    void getHistoryTextPart(scope.context, id, offset, field).then(result => {
      if (!cancelled && isCurrent() && result.context === scope.context && result.revision === scope.revision && result.id === id) setPart(result);
    }, problem => { if (!cancelled && isCurrent()) setError(t(String(problem))); });
    return () => { cancelled = true; };
  }, [scope.context, scope.revision, id, field, offset, retry]);
  return <section className="history-text-reader" aria-label={t(field === "text" ? "Resultado" : "Original")}>
    <h3>{t(field === "text" ? "Resultado" : "Original")}</h3>
    {error ? <><p role="alert" className="error">{error}</p><Button onClick={() => setRetry(value => value + 1)}>{t("Tentar novamente")}</Button></>
      : part ? <p className="history-text">{part.text || t("Sem texto")}</p> : <p role="status" className="hint">{t("Carregando…")}</p>}
    <div className="history-entry-actions">
      <Button variant="text" disabled={!part || offset === 0} onClick={() => setOffset(value => Math.max(0, value - 4000))}>{t("Trecho anterior")}</Button>
      <Button variant="text" disabled={!part?.hasMore} onClick={() => part && setOffset(part.nextOffset)}>{t("Próximo trecho")}</Button>
    </div>
  </section>;
}

export function HistoryComparison({ entry, scope, isCurrent }: {
  entry: HistoryEntry; scope: HistoryScope; isCurrent: () => boolean;
}) {
  return <div className="history-comparison">
    {!entry.hasOriginal && <p className="hint">{t("O original não está disponível para este registro.")}</p>}
    {entry.hasOriginal && !entry.originalDiffers && <p className="hint">{t("O original e o resultado são iguais.")}</p>}
    <div className={entry.originalDiffers ? "history-text-columns" : ""}>
      {entry.originalDiffers && <HistoryTextReader scope={scope} id={entry.id} field="transcript" isCurrent={isCurrent} />}
      <HistoryTextReader scope={scope} id={entry.id} field="text" isCurrent={isCurrent} />
    </div>
  </div>;
}
