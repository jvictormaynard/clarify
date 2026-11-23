import { useState } from "react";
import { t } from "../i18n";
import type { SettingsController } from "../settings/use-settings";
import { Button } from "./ui";

export function InputMonitoringButton({ controller, disabled }: {
  controller: Pick<SettingsController, "state" | "run">;
  disabled?: boolean;
}) {
  const [pending, setPending] = useState(false);
  const status = controller.state?.inputMonitoringStatus;
  if (status !== "request" && status !== "settings") return null;
  return <Button
    variant="ghost"
    loading={pending}
    disabled={disabled || pending}
    onClick={async () => {
      setPending(true);
      try {
        await controller.run("inputMonitoringCommand", status === "request" ? "request" : "open");
      } finally {
        setPending(false);
      }
    }}
  >{t(status === "request" ? "Permitir atalhos globais" : "Abrir Monitoramento de Entrada")}</Button>;
}
