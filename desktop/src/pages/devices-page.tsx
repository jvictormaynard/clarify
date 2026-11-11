import type { SettingsPageProps } from "../settings/use-settings";
import { ComputerAccess } from "../components/computer-access";
import { IPhoneDemo } from "../components/iphone-demo";
import { MobileAppDownload } from "../components/mobile-app-card";
import { Section } from "../components/ui";
import { t } from "../i18n";

export function DevicesPage({ controller }: SettingsPageProps) {
  return <><Section title={t("Clarify para iPhone")} grouped={false}><div className="mobile-device-guide"><IPhoneDemo /><div className="mobile-device-download"><MobileAppDownload /></div></div></Section><ComputerAccess controller={controller} /></>;
}
