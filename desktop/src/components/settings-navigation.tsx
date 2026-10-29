import { t } from "../i18n";
import type { Ref } from "react";
import { Settings2 } from "lucide-react";
import type { PageId, SettingsPage } from "../settings/navigation";
import { ScrollArea } from "./primitives/scroll-area";

const groups = () => [
  { id: "workspace", label: undefined },
  { id: "library", label: t("Biblioteca") },
];

export function SettingsNavigation({ pages, activePage, version, onNavigate, onOpenSettings, settingsButtonRef }: {
  pages: readonly SettingsPage[];
  activePage: PageId;
  version?: string;
  onNavigate: (id: PageId) => Promise<unknown>;
  onOpenSettings: () => void;
  settingsButtonRef?: Ref<HTMLButtonElement>;
}) {
  const navigationItems = (groupId: string) => pages.filter(item => item.group === groupId).map(({ id, label, icon: Icon }) => <button type="button"
    key={id} className="navigation-item" aria-label={label} title={label}
    aria-current={id === activePage ? "page" : undefined} onClick={() => void onNavigate(id)}>
    <Icon size={16} strokeWidth={2} aria-hidden /><span>{label}</span>
  </button>);

  return <>
    <nav aria-label={t("Configurações")}>
      <ScrollArea hideScrollbars scrollFade scrollFadePadding={false} viewportTabIndex={-1}
        className="h-auto min-h-0 flex-1 [&>[data-slot=scroll-area-viewport]]:[--fade-size:0.75rem]">
        <div className="settings-navigation-content">
          <div className="navigation-groups">
            {groups().map(group => <div className={`navigation-group navigation-group-${group.id}`} key={group.id} role="group" aria-label={group.label}>
              {group.label && <div className="navigation-group-label" aria-hidden="true">{group.label}</div>}
              {navigationItems(group.id)}
            </div>)}
          </div>
        </div>
      </ScrollArea>
      <div className="navigation-group navigation-group-account">
        <button ref={settingsButtonRef} type="button" className="navigation-item" aria-label={t("Configurações")} title={t("Configurações")}
          onClick={onOpenSettings}>
          <Settings2 size={16} strokeWidth={2} aria-hidden /><span>{t("Configurações")}</span>
        </button>
      </div>
    </nav>
    <div className="sidebar-meta"><span>Clarify</span>{version && <code>v{version}</code>}</div>
  </>;
}
