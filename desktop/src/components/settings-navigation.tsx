import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Search, X } from "lucide-react";
import { t } from "../i18n";
import type { PageId, SettingsPage } from "../settings/navigation";
import { searchSettings, type SettingsSearchResult } from "../settings/search";
import { Button } from "./primitives/button";

const groups = () => [
  { id: "settings", label: undefined },
  { id: "workspace", label: t("Ações rápidas") },
  { id: "library", label: t("Dicionário e snippets") },
  { id: "account", label: t("Conta Clarify") },
];

export function SettingsNavigation({ pages, activePage, version, onNavigate, onSearchNavigate, onSearchInteraction }: {
  pages: readonly SettingsPage[];
  activePage: PageId;
  version?: string;
  onNavigate: (id: PageId) => Promise<unknown>;
  onSearchNavigate: (result: SettingsSearchResult) => void;
  onSearchInteraction: () => void;
}) {
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const searching = query.trim().length > 0;
  const results = searchSettings(query, pages);
  const selected = Math.min(highlight, Math.max(results.length - 1, 0));

  useEffect(() => {
    const find = (event: globalThis.KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing) return;
      const slash = event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey;
      const shortcut = event.key.toLowerCase() === "f" && (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey;
      if (!slash && !shortcut) return;
      const target = event.target;
      if (target instanceof HTMLElement && (
        target.closest('[role="dialog"], [aria-modal="true"], [data-slot$="popup"]') ||
        (slash && (target.isContentEditable || /^(INPUT|TEXTAREA)$/.test(target.tagName)))
      )) return;
      event.preventDefault(); onSearchInteraction(); setExpanded(true);
      input.current?.focus(); input.current?.select();
    };
    window.addEventListener("keydown", find);
    return () => window.removeEventListener("keydown", find);
  }, [onSearchInteraction]);
  useEffect(() => { if (expanded) input.current?.focus(); }, [expanded]);
  useEffect(() => {
    document.getElementById(`settings-search-${results[selected]?.id}`)?.scrollIntoView({ block: "nearest" });
  }, [selected, query]);

  const choose = (result: SettingsSearchResult) => {
    setQuery(""); setHighlight(0); setExpanded(false); onSearchNavigate(result);
  };
  const keyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      event.preventDefault(); onSearchInteraction(); setQuery(""); setExpanded(false); setHighlight(0); input.current?.blur();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setHighlight(Math.max(0, Math.min(results.length - 1, selected + (event.key === "ArrowDown" ? 1 : -1))));
    } else if (event.key === "Enter" && results[selected]) {
      event.preventDefault(); choose(results[selected]);
    }
  };

  return <>
    <nav aria-label={t("Configurações")} className={expanded ? "search-expanded" : undefined}>
      <div className="settings-search">
        <Search size={16} aria-hidden />
        <input ref={input} type="search" role="combobox" autoComplete="off" spellCheck={false}
          aria-label={t("Buscar configurações")} placeholder={t("Buscar")}
          aria-autocomplete="list" aria-expanded={searching && results.length > 0}
          aria-controls={searching && results.length ? "settings-search-results" : undefined}
          aria-activedescendant={searching && results[selected] ? `settings-search-${results[selected].id}` : undefined}
          value={query} onFocus={() => { onSearchInteraction(); setExpanded(true); }} onBlur={() => { if (!searching) setExpanded(false); }}
          onChange={event => { onSearchInteraction(); setQuery(event.currentTarget.value); setHighlight(0); }} onKeyDown={keyDown} />
        {searching ? <Button variant="ghost-muted" size="icon-micro" aria-label={t("Limpar busca")}
          onClick={() => { onSearchInteraction(); setQuery(""); setHighlight(0); input.current?.focus(); }}><X size={12} /></Button>
          : <kbd aria-hidden="true">/</kbd>}
      </div>
      <Button variant="ghost" className={expanded ? "compact-search hidden" : "compact-search hidden max-md:flex"} aria-label={t("Buscar configurações")}
        title={t("Buscar configurações")} onClick={() => setExpanded(true)}><Search size={16} /></Button>
      {searching ? <div className="settings-search-results" id="settings-search-results" role={results.length ? "listbox" : undefined} aria-label={results.length ? t("Configurações") : undefined}>
        {results.length ? results.map((result, index) => <button type="button" role="option"
          id={`settings-search-${result.id}`} key={result.id} aria-selected={selected === index} tabIndex={-1}
          onMouseMove={() => setHighlight(index)} onMouseDown={event => event.preventDefault()} onClick={() => choose(result)}>
          <result.page.icon size={16} aria-hidden />
          <span><span>{result.title}</span><small>{result.page.label}</small></span>
        </button>) : <p role="status">{t("Nenhum resultado encontrado.")}</p>}
      </div> : <div className="navigation-groups">
        {groups().map(group => <div className={`navigation-group navigation-group-${group.id}`} key={group.id}>
          {group.label && <div className="navigation-group-label" aria-hidden="true">{group.label}</div>}
          {pages.filter(item => item.group === group.id).map(({ id, label, icon: Icon }) => <button type="button"
            key={id} className="navigation-item" aria-label={label} title={label}
            aria-current={id === activePage ? "page" : undefined} onClick={() => void onNavigate(id)}>
            <Icon size={16} strokeWidth={2} aria-hidden /><span>{label}</span>
          </button>)}
        </div>)}
      </div>}
    </nav>
    <div className="sidebar-meta"><span>Clarify</span>{version && <code>v{version}</code>}</div>
  </>;
}
