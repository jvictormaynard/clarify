import type { SettingsPageProps } from "../settings/use-settings";
import { ComputerAccess } from "../components/computer-access";

export function DevicesPage({ controller }: SettingsPageProps) {
  return <ComputerAccess controller={controller} />;
}
