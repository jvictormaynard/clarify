import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { HistoryPage } from "./history-page";
import { MobileAppCard } from "../components/mobile-app-card";

export function HomePage({ controller }: SettingsPageProps) {
  return <>
    <MobileAppCard paired={!!controller.state.computerState?.devices?.length} />
    <section className="home-history" aria-label={t("Histórico")}>
      <HistoryPage controller={controller} />
    </section>
  </>;
}
