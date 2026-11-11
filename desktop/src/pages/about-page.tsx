import logo from "../../src-tauri/icons/clarify.png";
import type { SettingsPageProps } from "../settings/use-settings";
import { t } from "../i18n";

export function AboutPage({ controller }: SettingsPageProps) {
  return <section className="about-page" aria-label="Clarify">
    <img src={logo} width="48" height="48" alt="" />
    <h3>Clarify</h3>
    <p>{t("Versão")} {controller.state.applicationVersion || "—"}</p>
  </section>;
}
