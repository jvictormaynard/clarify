import { t } from "../i18n";
import type { PageId, SettingsPage } from "../settings/navigation";
import { Button } from "./primitives/button";

const groups = () => [
  { id: "workspace", label: t("Ações rápidas") },
  { id: "library", label: t("Dicionário e snippets") },
  { id: "settings", label: t("Preferências") },
  { id: "account", label: t("Conta Clarify") },
];

export function SettingsNavigation({ pages, activePage, version, onNavigate }: {
  pages: readonly SettingsPage[];
  activePage: PageId;
  version?: string;
  onNavigate: (id: PageId) => Promise<unknown>;
}) {
  return <>
    <nav aria-label={t("Configurações")}>
      {groups().map(group => <div className={`navigation-group navigation-group-${group.id}`} key={group.id}>
        <div className="navigation-group-label" aria-hidden="true">{group.label}</div>
        {pages.filter(item => item.group === group.id).map(({ id, label, icon: Icon }) => <Button
          key={id}
          variant="ghost"
          className="h-8 w-full justify-start gap-2 rounded-lg px-2.5 py-1.25 text-[13px] font-normal text-[var(--sidebar-foreground)] hover:bg-[var(--sidebar-row-hover)] aria-[current=page]:border-[var(--border-subtle)] aria-[current=page]:bg-[var(--sidebar-row-active)] aria-[current=page]:text-accent-foreground"
          aria-label={label}
          title={label}
          aria-current={id === activePage ? "page" : undefined}
          onClick={() => void onNavigate(id)}
        ><Icon size={16} strokeWidth={1.6} aria-hidden /><span>{label}</span></Button>)}
      </div>)}
    </nav>
    <div className="sidebar-meta"><span>Clarify</span>{version && <code>v{version}</code>}</div>
  </>;
}
