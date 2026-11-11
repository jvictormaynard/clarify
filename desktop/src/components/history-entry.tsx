import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Check, Copy, LoaderCircle, Trash2 } from "lucide-react";
import { t } from "../i18n";
import { Button } from "./ui";
import { CollapsiblePanel } from "./primitives/collapsible";
import { Dialog, DialogDescription, DialogHeader, DialogPopup, DialogTitle } from "./primitives/dialog";
import { copyHistoryText, getHistoryTextPart, type HistoryEntry, type HistoryScope, type HistoryTextField } from "../settings/bridge";

export type HistoryEntryExtension = (entry: HistoryEntry, scope: HistoryScope) => ReactNode;

export function HistoryEntryActions({ entry, scope, isCurrent, onDelete }: {
  entry: HistoryEntry; scope: HistoryScope; isCurrent: () => boolean; onDelete: () => void;
}) {
  const [copying, setCopying] = useState<HistoryTextField | null>(null);
  const [copied, setCopied] = useState(false);
  const feedbackTimer = useRef<number | null>(null);
  const [error, setError] = useState("");
  const pending = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => {
    mounted.current = false;
    if (feedbackTimer.current !== null) window.clearTimeout(feedbackTimer.current);
  }; }, []);
  const active = () => mounted.current && isCurrent();
  const copy = async (field: HistoryTextField) => {
    if (pending.current || !active()) return;
    pending.current = true;
    if (feedbackTimer.current !== null) window.clearTimeout(feedbackTimer.current);
    setCopying(field); setCopied(false); setError("");
    try {
      const result = await copyHistoryText(scope, entry.id, field, active);
      if (active() && result?.context === scope.context && result.revision === scope.revision && result.id === entry.id) {
        setCopied(true);
        feedbackTimer.current = window.setTimeout(() => { if (active()) setCopied(false); }, 1800);
      }
    } catch (problem) {
      if (active()) setError(t(String(problem)));
    } finally {
      pending.current = false;
      if (active()) setCopying(null);
    }
  };
  return <>
    <div className="history-row-tools">
      <Button variant="ghost" className="history-icon-action h-[30px] w-[30px] p-0 pointer-coarse:h-11 pointer-coarse:w-11" aria-label={t(copied ? "Copiado." : "Copiar resultado")} title={t("Copiar resultado")} disabled={copying !== null} aria-busy={copying !== null} onClick={() => void copy("text")}>
        {copying !== null ? <LoaderCircle size={16} className="spin" aria-hidden="true" /> : copied ? <Check size={16} className="history-copy-glyph" aria-hidden="true" /> : <Copy size={16} className="history-copy-glyph" aria-hidden="true" />}
      </Button>
      <Button variant="ghost" className="history-icon-action history-delete h-[30px] w-[30px] p-0 pointer-coarse:h-11 pointer-coarse:w-11" aria-label={t("Excluir transcrição")} title={t("Excluir transcrição")} onClick={onDelete}><Trash2 size={16} aria-hidden="true" /></Button>
    </div>
    {error && <p role="alert" className="error">{error}</p>}
  </>;
}

type HistoryTextPart = { text: string; nextOffset: number; hasMore: boolean };
type HistoryReaderProps = { scope: HistoryScope; id: string; field: HistoryTextField; isCurrent: () => boolean };

function FullHistoryText({ scope, id, field, isCurrent, initial }: HistoryReaderProps & { initial: HistoryTextPart }) {
  const [parts, setParts] = useState([initial.text]);
  const [part, setPart] = useState(initial);
  const [offset, setOffset] = useState<number | null>(null);
  const [error, setError] = useState("");
  const viewport = useRef<HTMLDivElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const current = useRef(isCurrent);
  current.current = isCurrent;
  useEffect(() => {
    if (offset === null) return;
    let cancelled = false;
    void getHistoryTextPart(scope.context, id, offset, field).then(result => {
      if (!cancelled && current.current() && result.context === scope.context && result.revision === scope.revision && result.id === id) {
        setParts(value => [...value, result.text]); setPart(result); setOffset(null);
      }
    }, problem => { if (!cancelled && current.current()) { setError(t(String(problem))); setOffset(null); } });
    return () => { cancelled = true; };
  }, [scope.context, scope.revision, id, field, offset]);
  useEffect(() => {
    if (!part.hasMore || offset !== null || error || !end.current || !viewport.current) return;
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting) && current.current()) setOffset(part.nextOffset);
    }, { root: viewport.current, rootMargin: "160px" });
    observer.observe(end.current);
    return () => observer.disconnect();
  }, [part, offset, error]);
  return <div className="history-full-reader" ref={viewport} tabIndex={0}>
    <p className="history-full-text">{parts.join("") || t("Sem texto")}</p>
    <div ref={end} className="history-reader-end" />
    {offset !== null && <span role="status" aria-label={t("Carregando…")}><LoaderCircle size={16} className="spin" aria-hidden="true" /></span>}
    {error && <><p role="alert" className="error">{error}</p><Button variant="text" onClick={() => { setError(""); setOffset(part.nextOffset); }}>{t("Tentar novamente")}</Button></>}
  </div>;
}

function HistoryTextReader({ scope, id, field, isCurrent }: HistoryReaderProps) {
  const [part, setPart] = useState<HistoryTextPart | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [open, setOpen] = useState(false);
  const readMore = useRef<HTMLButtonElement>(null);
  const preview = useRef<HTMLParagraphElement>(null);
  const [overflowing, setOverflowing] = useState(false);
  useEffect(() => {
    if (!preview.current) return;
    const element = preview.current;
    const measure = () => setOverflowing(element.scrollHeight > element.clientHeight);
    measure();
    let frame = 0;
    const observer = new ResizeObserver(() => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(measure);
    });
    observer.observe(element);
    return () => { observer.disconnect(); window.cancelAnimationFrame(frame); };
  }, [part]);
  useEffect(() => {
    let cancelled = false;
    setPart(null); setError(""); setOpen(false);
    void getHistoryTextPart(scope.context, id, 0, field).then(result => {
      if (!cancelled && isCurrent() && result.context === scope.context && result.revision === scope.revision && result.id === id) setPart(result);
    }, problem => { if (!cancelled && isCurrent()) setError(t(String(problem))); });
    return () => { cancelled = true; };
  }, [scope.context, scope.revision, id, field, retry]);
  const title = t(field === "text" ? "Resultado" : "Original");
  const longer = !!part && (part.hasMore || part.text.length > 600 || overflowing);
  return <section className="history-text-reader" aria-label={title}>
    <h3>{title}</h3>
    {error ? <><p role="alert" className="error">{error}</p><Button onClick={() => setRetry(value => value + 1)}>{t("Tentar novamente")}</Button></>
      : part ? <p ref={preview} className="history-text history-text-preview">{part.text ? part.text.slice(0, 600) + (longer ? "…" : "") : t("Sem texto")}</p> : <p role="status" className="hint">{t("Carregando…")}</p>}
    {longer && <Button variant="text" ref={readMore} className="history-read-more" onClick={() => setOpen(true)}>{t("Ler mais")}</Button>}
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogPopup className="history-full-dialog" finalFocus={readMore}>
        <DialogHeader><DialogTitle>{title}</DialogTitle><DialogDescription className="sr-only">{t("Texto completo")}</DialogDescription></DialogHeader>
        {part && <FullHistoryText scope={scope} id={id} field={field} isCurrent={isCurrent} initial={part} />}
      </DialogPopup>
    </Dialog>
  </section>;
}

export function HistoryDetailsPanel({ children }: { children: ReactNode }) {
  const cleanup = useRef<(() => void) | null>(null);
  const measureContent = useCallback((element: HTMLDivElement | null) => {
    cleanup.current?.();
    cleanup.current = null;
    if (!element) return;
    const panel = element.parentElement!;
    let frame = 0;
    const measure = () => panel.style.setProperty("--history-detail-height", `${element.getBoundingClientRect().height}px`);
    measure();
    const observer = new ResizeObserver(() => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(measure);
    });
    observer.observe(element);
    cleanup.current = () => { observer.disconnect(); window.cancelAnimationFrame(frame); };
  }, []);
  return <CollapsiblePanel className="history-detail-panel h-[var(--history-detail-height,var(--collapsible-panel-height))]"><div className="history-detail" ref={measureContent}>{children}</div></CollapsiblePanel>;
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
