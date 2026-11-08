import type { RefObject } from "react";
import { AlertCircle } from "lucide-react";
import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { getSettingsSections } from "../settings/navigation";
import { GeneralPage } from "../pages/general-page";
import { ModelsPage } from "../pages/models-page";
import { ShortcutsPage } from "../pages/shortcuts-page";
import { PrivacyPage } from "../pages/privacy-page";
import { AccountPage } from "../pages/account-page";
import { DevicesPage } from "../pages/devices-page";
import { PracticeEntry } from "./dictation-practice";
import { Button } from "./ui";
import { Dialog, DialogPopup, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "./primitives/dialog";

const sections = { general: GeneralPage, devices: DevicesPage, models: ModelsPage, shortcuts: ShortcutsPage, privacy: PrivacyPage, account: AccountPage };

export function SettingsDialog({ controller: c, returnFocus }: SettingsPageProps & { returnFocus: RefObject<HTMLButtonElement | null> }) {
  const managed = !!(c.state.accountState?.managed || c.state.accountState?.signedIn);
  const section = managed && c.settingsSection === "models" ? "account" : c.settingsSection;
  const Page = sections[section];
  const info = getSettingsSections().find(item => item.id === section)!;
  const dirty = c.hasSettingsDrafts();
  return <Dialog open={c.settingsOpen} onOpenChange={open => { if (!open) c.requestCloseSettings(); }}>
    <DialogPopup className="settings-dialog max-w-5xl" bottomStickOnMobile={false} finalFocus={returnFocus}>
      <DialogHeader>
        <DialogTitle>{t("Configurações")}</DialogTitle>
        <DialogDescription className="sr-only">{t("Preferências, modelos, atalhos e conta do Clarify.")}</DialogDescription>
      </DialogHeader>
      <div className="settings-dialog-layout">
        <nav className="settings-dialog-navigation" aria-label={t("Seções das configurações")}>
          {getSettingsSections().filter(item => !managed || item.id !== "models").map(({ id, label, icon: Icon }) =>
            <button key={id} type="button" className="navigation-item" aria-label={label} title={label}
              aria-current={section === id ? "page" : undefined} onClick={() => void c.navigate(id)}>
              <Icon size={16} aria-hidden /><span>{label}</span>
            </button>)}
        </nav>
        <div className="settings-dialog-content">
          <h2 className="settings-dialog-section-title">{info.label}</h2>
          {c.error && <div role="alert" className="error settings-error"><AlertCircle size={17} /><span>{t(c.error)}</span></div>}
          <div className="page-content"><Page controller={c} />
            {section === "general" && <PracticeEntry controller={c} />}
          </div>
        </div>
      </div>
      <DialogFooter>
        {c.settingsDismissRequested && <span className="settings-dialog-unsaved" role="status">{t("Há alterações não salvas nas configurações.")}</span>}
        {c.settingsDismissRequested && <Button variant="ghost" onClick={() => c.setSettingsDismissRequested(false)}>{t("Continuar editando")}</Button>}
        {dirty ? <>
          <Button variant="ghost" disabled={c.saving || c.discardingDrafts}
            onClick={() => void c.discardSettings(c.settingsDismissRequested)}>{t("Descartar")}</Button>
          <Button variant="primary" aria-label={t("Salvar alterações")} disabled={c.saving || c.discardingDrafts}
            onClick={() => void c.saveSettings(c.settingsDismissRequested)}>{t("Salvar")}</Button>
        </> : <Button onClick={c.requestCloseSettings}>{t("Concluído")}</Button>}
      </DialogFooter>
    </DialogPopup>
  </Dialog>;
}
