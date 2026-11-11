import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { Search } from "lucide-react";
import { Button, Input } from "./ui";
import "../styles/page-search.css";

export function PageSearch({ label, query, onQueryChange, maxLength, interactionBoundary }: {
  label: string; query: string; onQueryChange: (value: string) => void; maxLength?: number;
  interactionBoundary?: RefObject<HTMLElement | null>;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const field = useRef<HTMLInputElement>(null);
  const id = useId();
  const close = useCallback((returnFocus = false) => {
    setOpen(false);
    onQueryChange("");
    if (returnFocus) trigger.current?.focus();
  }, [onQueryChange]);
  useLayoutEffect(() => { if (open) field.current?.focus(); }, [open]);
  useEffect(() => {
    if (!open) return;
    // Finish the clicked action before clearing a filter that can move its row.
    const outside = (event: MouseEvent) => {
      // Modal content lives in a portal outside the page. Keep its source rows.
      if (document.querySelector('[data-slot="dialog-popup"]:not([inert])')) return;
      if (event.target instanceof Node && !root.current?.contains(event.target) && !interactionBoundary?.current?.contains(event.target)) close();
    };
    document.addEventListener("click", outside);
    return () => document.removeEventListener("click", outside);
  }, [open, close, interactionBoundary]);
  return <div className="page-search" ref={root} data-open={open || undefined}>
    <Button className="page-search-trigger" variant="ghost" ref={trigger} aria-label={label} title={label}
      aria-expanded={open} aria-controls={id} onClick={() => open ? close(true) : setOpen(true)}>
      <Search size={16} aria-hidden="true" />
    </Button>
    {open && <Input id={id} ref={field} unstyled type="search" maxLength={maxLength} aria-label={label} placeholder={label}
      value={query} onChange={event => onQueryChange(event.target.value)} onKeyDown={event => {
        if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(true); }
      }} />}
  </div>;
}
