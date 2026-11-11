import { useRef, useState, type ReactNode } from "react";
import { RefreshCw } from "lucide-react";
import { t } from "../i18n";
import { Button } from "./ui";
import { PageSearch } from "./page-search";
import { FeatureGuide, FeatureGuideCard, type GuideKind } from "./feature-guide";
import "../styles/libraries.css";

export function LibraryPageHeader({ kind, title, children }: { kind: GuideKind; title: string; children: ReactNode }) {
  return <>
    <header className="workspace-page-header library-page-header">
      <div className="workspace-page-heading"><h1>{title}</h1><FeatureGuide kind={kind} /></div>
      {children}
    </header>
    <FeatureGuideCard kind={kind} />
  </>;
}

export function LibraryToolbar({ label, query, onQueryChange, refreshLabel, onRefresh, busy = false }: {
  label: string; query: string; onQueryChange: (value: string) => void;
  refreshLabel: string; onRefresh: () => Promise<unknown>; busy?: boolean;
}) {
  const [refreshing, setRefreshing] = useState(false);
  const pending = useRef(false);
  const refresh = async () => {
    if (pending.current || busy) return;
    pending.current = true;
    setRefreshing(true);
    try { await onRefresh(); }
    finally { pending.current = false; setRefreshing(false); }
  };
  return <div className="library-toolbar" role="group" aria-label={t("Buscar")}>
    <PageSearch label={label} query={query} onQueryChange={onQueryChange} />
    <Button variant="ghost" className="library-refresh" aria-label={refreshLabel} title={refreshLabel}
      disabled={busy || refreshing} onClick={() => void refresh()}><RefreshCw size={16} className={refreshing || busy ? "spin" : undefined} aria-hidden /></Button>
  </div>;
}
