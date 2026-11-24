import { t } from "../i18n";
import { useState } from "react";
import { ArrowRight } from "lucide-react";
import { Button, Field, Picker, Row, SettingsDisclosure } from "./ui";
import type { SettingsPageProps } from "../settings/use-settings";

export function WorkflowRoute({ controller }: SettingsPageProps) {
  const {
    state,
    run,
    openModelServices,
    routeOverride,
    setRouteOverride,
    selectRouteProvider,
  } = controller;
  const [openCodeDraftScope, setOpenCodeDraftScope] = useState<string>();
  const pendingOpenCode = openCodeDraftScope === state.selectedScope && state.routeProviderId !== "opencode";
  const openCode = state.personalSetupState?.textOptions.find(option => option.id === "opencode");
  const appleClarity = !pendingOpenCode && state.routeProviderId === "apple_clarity";
  const loadOpenCode = () => run("personalSetupCommand", "connect_opencode", "{}");
  const chooseProvider = (provider: string) => {
    if (provider === "opencode" && state.routeProviderId !== provider) {
      setOpenCodeDraftScope(state.selectedScope);
      if (openCode?.runtimeInstalled && !openCode.models?.length && !state.personalSetupState?.busy) {
        void loadOpenCode();
      }
      return;
    }
    setOpenCodeDraftScope(undefined);
    void selectRouteProvider(provider);
  };
  return (
    <>
      <Row title={t("Serviço")}>
        <Picker
          label={t("Serviço")}
          value={pendingOpenCode ? "opencode" : state.routeProviderId}
          options={state.routeProviders}
          onChange={chooseProvider}
        />
      </Row>
      {!pendingOpenCode && state.routeProviderId === "chatgpt" && (
        <div>
          <p className="hint" role="status">{t(state.chatgptState?.connected && state.chatgptState.planEnabled
            ? "Usando seu plano ChatGPT" : "Conecte o ChatGPT e permita o uso do plano.")}</p>
          <Button variant="text" onClick={() => void run("chatgptCommand", "manage_usage", "")}>
            {t("Gerenciar uso no ChatGPT")}
          </Button>
        </div>
      )}
      {appleClarity && (
        <p className="hint" role="status">
          {t(["error", "empty"].includes(state.routeModelStatus)
            ? "apple_clarity_unavailable" : "apple_clarity_local")}
        </p>
      )}
      <Row title={t("Modelo")}>
        <Picker
          label={t("Modelo")}
          value={pendingOpenCode ? "" : state.routeModelId}
          options={pendingOpenCode ? openCode?.models ?? [] : state.routeModelOptions}
          onChange={(value) => {
            if (!pendingOpenCode) {
              void run("setRouteModelId", value);
              return;
            }
            void run("savePreference", "setOpenCodeRouteModel", [state.selectedScope, value])
              .then(saved => { if (saved) setOpenCodeDraftScope(undefined); });
          }}
          onRefresh={() => void (pendingOpenCode ? loadOpenCode() : run("refreshRouteModels"))}
          busy={pendingOpenCode ? state.personalSetupState?.busy : state.routeModelStatus === "loading"}
          empty={
            state.routeProviderId === "local_asr"
              ? t("Nenhum modelo instalado.")
              : t("Nenhum modelo disponível. Verifique o serviço.")
          }
        />
      </Row>
      {pendingOpenCode && state.personalSetupState?.error && (
        <p role="status" className="hint">{t(state.personalSetupState.error)}</p>
      )}
      {pendingOpenCode && openCode?.runtimeInstalled === false && (
        <Button onClick={() => void loadOpenCode()} disabled={state.personalSetupState?.busy}>
          {t("setup_install_opencode")}
        </Button>
      )}
      {!pendingOpenCode && !appleClarity && ["empty", "not_configured", "error"].includes(
        state.routeModelStatus,
      ) && (
        <Button variant="text" onClick={() => void openModelServices(state.routeProviderId)}>
          {state.routeModelStatus === "not_configured"
            ? t("Conectar serviço")
            : t("Gerenciar modelos e serviços")}{" "}
          <ArrowRight size={15} />
        </Button>
      )}
      {!pendingOpenCode && !appleClarity && !["local_asr", "chatgpt", "opencode"].includes(state.routeProviderId) && (
        <SettingsDisclosure key={state.selectedScope} title={t("Modelo e endereço personalizados")}>
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
        </SettingsDisclosure>
      )}
    </>
  );
}
