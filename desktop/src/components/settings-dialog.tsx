import { useLayoutEffect, useRef, type RefObject } from "react";
import { AlertCircle, LoaderCircle } from "lucide-react";
import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { getSettingsSections } from "../settings/navigation";
import { DictationPage } from "../pages/dictation-page";
import { GeneralPage, TextLanguagePreferences } from "../pages/general-page";
import { ModelsPage } from "../pages/models-page";
import { ShortcutsPage } from "../pages/shortcuts-page";
import { PrivacyPage } from "../pages/privacy-page";
import { AccountPage } from "../pages/account-page";
import { AboutPage } from "../pages/about-page";
import { DevicesPage } from "../pages/devices-page";
import { PracticeEntry } from "./dictation-practice";
import { Button } from "./ui";
import { Dialog, DialogPopup, DialogTitle, DialogDescription, DialogFooter } from "./primitives/dialog";

function GeneralSettings({ controller }: SettingsPageProps) {
  return <><ShortcutsPage controller={controller} /><DictationPage controller={controller} /><TextLanguagePreferences controller={controller} /></>;
}

const sections = { dictation: GeneralSettings, general: GeneralPage, devices: DevicesPage, models: ModelsPage, shortcuts: ShortcutsPage, privacy: PrivacyPage, account: AccountPage, about: AboutPage };

export function SettingsDialog({ controller: c, returnFocus }: SettingsPageProps & { returnFocus: RefObject<HTMLButtonElement | null> }) {
  const managed = !!(c.state.accountState?.managed || c.state.accountState?.signedIn);
  const section = managed && c.settingsSection === "models" ? "account" : c.settingsSection;
  const content = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => { if (content.current) content.current.scrollTop = 0; }, [section]);
  const Page = sections[section];
  const info = getSettingsSections().find(item => item.id === section)!;
  const dirty = c.hasSettingsDrafts();
  return <Dialog open={c.settingsOpen} onOpenChange={open => { if (!open) c.requestCloseSettings(); }}>
    <DialogPopup className="settings-dialog max-w-[960px] w-[min(960px,calc(100vw-2rem))]" bottomStickOnMobile={false} finalFocus={returnFocus}>
      <DialogTitle className="sr-only">{t("Configurações")}</DialogTitle>
      <DialogDescription className="sr-only">{t("Preferências, modelos, atalhos e conta do Clarify.")}</DialogDescription>
      <div className="settings-dialog-layout">
        <nav className="settings-dialog-navigation" aria-label={t("Seções das configurações")}>
          <span className="settings-dialog-label" aria-hidden="true">{t("Configurações")}</span>
          {getSettingsSections().filter(item => item.id !== "shortcuts" && (!managed || item.id !== "models")).map(({ id, label, icon: Icon }) =>
            <button key={id} type="button" className="navigation-item" aria-label={label} title={label}
              aria-current={section === id ? "page" : undefined} onClick={() => void c.navigate(id)}>
              <Icon size={16} aria-hidden /><span>{label}</span>
            </button>)}
        </nav>
        <div className="settings-dialog-content" ref={content}>
          <header className="workspace-page-header settings-page-header"><info.icon size={24} aria-hidden /><h2>{info.label}</h2></header>
          {c.error && <div role="alert" className="error settings-error"><AlertCircle size={17} /><span>{t(c.error)}</span></div>}
          <div className="page-content">{c.routeLoading && section === "dictation" ? <div className="connection" role="status"><LoaderCircle size={22} className="spin" />{t("Carregando…")}</div> : <Page controller={c} />}
            {(section === "general" || section === "dictation") && <PracticeEntry controller={c} />}
          </div>
        </div>
      </div>
      <span className="sr-only" role="status">{c.saved ? t("Alterações salvas") : ""}</span>
      {(dirty || c.settingsDismissRequested) && <DialogFooter>
        {c.settingsDismissRequested && <span className="settings-dialog-unsaved" role="status">{t("Há alterações não salvas nas configurações.")}</span>}
        {c.settingsDismissRequested && <Button variant="ghost" onClick={() => c.setSettingsDismissRequested(false)}>{t("Continuar editando")}</Button>}
        {dirty ? <>
          <Button variant="ghost" disabled={c.saving || c.discardingDrafts || c.routeLoading}
            onClick={() => void c.discardSettings(c.settingsDismissRequested)}>{t("Descartar")}</Button>
          <Button variant="primary" aria-label={t("Salvar alterações")} disabled={c.saving || c.discardingDrafts || c.routeLoading}
            onClick={() => void c.saveSettings(c.settingsDismissRequested)}>{t("Salvar")}</Button>
        </> : <Button onClick={c.requestCloseSettings}>{t("Concluído")}</Button>}
      </DialogFooter>}
    </DialogPopup>
  </Dialog>;
}
