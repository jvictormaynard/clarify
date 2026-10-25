import { t } from "../i18n";
import { ArrowRight } from "lucide-react";
import { Button, Field, Picker, Row } from "./ui";
import type { SettingsPageProps } from "../settings/use-settings";

export function WorkflowRoute({ controller }: SettingsPageProps) {
  const {
    state,
    run,
    navigate,
    routeOverride,
    setRouteOverride,
    selectRouteProvider,
  } = controller;
  return (
    <>
      <Row title={t("Serviço")}>
        <Picker
          label={t("Serviço")}
          value={state.routeProviderId}
          options={state.routeProviders}
          onChange={(value) => void selectRouteProvider(value)}
        />
      </Row>
      <Row title={t("Modelo")}>
        <Picker
          label={t("Modelo")}
          value={state.routeModelId}
          options={state.routeModelOptions}
          onChange={(value) => void run("setRouteModelId", value)}
          onRefresh={() => void run("refreshRouteModels")}
          busy={state.routeModelStatus === "loading"}
          empty={
            state.routeProviderId === "local_asr"
              ? t("Nenhum modelo instalado.")
              : t("Nenhum modelo disponível. Verifique o serviço.")
          }
        />
      </Row>
      {["empty", "not_configured", "error"].includes(
        state.routeModelStatus,
      ) && (
        <Button variant="text" onClick={() => void navigate("models")}>
          {state.routeModelStatus === "not_configured"
            ? t("Conectar serviço")
            : t("Gerenciar modelos e serviços")}{" "}
          <ArrowRight size={15} />
        </Button>
      )}
      {state.routeProviderId !== "local_asr" && (
        <details key={state.selectedScope}>
          <summary>{t("Modelo e endereço personalizados")}</summary>
          <Field
            title={t("ID do modelo")}
            hint={t("Opcional: use um modelo que não aparece no catálogo.")}
            value={routeOverride?.model ?? state.routeModelId}
            onChange={(e) =>
              setRouteOverride({
                ...routeOverride,
                model: e.target.value,
              })
            }
          />
          <Field
            title={t("Endereço deste fluxo")}
            hint={t("Deixe vazio para usar o endereço do serviço.")}
            value={routeOverride?.endpoint ?? state.routeCustomEndpoint}
            onChange={(e) =>
              setRouteOverride({
                ...routeOverride,
                endpoint: e.target.value,
              })
            }
          />
        </details>
      )}
    </>
  );
}
