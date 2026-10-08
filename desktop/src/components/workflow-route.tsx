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
      <Row title="Serviço">
        <Picker
          label="Serviço"
          value={state.routeProviderId}
          options={state.routeProviders}
          onChange={(value) => void selectRouteProvider(value)}
        />
      </Row>
      <Row title="Modelo">
        <Picker
          label="Modelo"
          value={state.routeModelId}
          options={state.routeModelOptions}
          onChange={(value) => void run("setRouteModelId", value)}
          onRefresh={() => void run("refreshRouteModels")}
          busy={state.routeModelStatus === "loading"}
          empty={
            state.routeProviderId === "local_asr"
              ? "Nenhum modelo instalado."
              : "Nenhum modelo disponível. Verifique o serviço."
          }
        />
      </Row>
      {["empty", "not_configured", "error"].includes(
        state.routeModelStatus,
      ) && (
        <Button variant="text" onClick={() => void navigate("models")}>
          {state.routeModelStatus === "not_configured"
            ? "Conectar serviço"
            : "Gerenciar modelos e serviços"}{" "}
          <ArrowRight size={15} />
        </Button>
      )}
      {state.routeProviderId !== "local_asr" && (
        <details key={state.selectedScope}>
          <summary>Modelo e endereço personalizados</summary>
          <Field
            title="ID do modelo"
            hint="Opcional: use um modelo que não aparece no catálogo."
            value={routeOverride?.model ?? state.routeModelId}
            onChange={(e) =>
              setRouteOverride({
                model: e.target.value,
                endpoint: routeOverride?.endpoint ?? state.routeCustomEndpoint,
              })
            }
          />
          <Field
            title="Endereço deste fluxo"
            hint="Deixe vazio para usar o endereço do serviço."
            value={routeOverride?.endpoint ?? state.routeCustomEndpoint}
            onChange={(e) =>
              setRouteOverride({
                endpoint: e.target.value,
                model: routeOverride?.model ?? state.routeModelId,
              })
            }
          />
        </details>
      )}
    </>
  );
}
