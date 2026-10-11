import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import {
  Button,
  Field,
  Input,
  Picker,
  Row,
  Section,
  Toggle,
} from "../components/ui";
import { Check, LoaderCircle, Download } from "lucide-react";

export function ModelsPage({ controller }: SettingsPageProps) {
  const {
    state,
    run,
    setConfirmAction,
    apiKey,
    setApiKey,
    endpoint,
    setEndpoint,
    busy,
    selectProvider,
    validateProvider,
    useLocalModel,
  } = controller;
  const requirements = [
    ...new Set(state.localAsrRequirementsList.filter(Boolean)),
  ];
  return (
    <>
      <Section
        title={
          <>{t("Modelos locais")}<span className="badge">{t("No seu computador")}</span>
          </>
        }
      >
        <p className="hint">{t("Transcreva sem enviar o áudio para um serviço externo.")}</p>
        <Row title={t("Modelo")}>
          <Picker
            label={t("Modelo local")}
            disabled={state.localAsrBusy || state.localBenchmarkBusy}
            value={String(state.localProfileIndex)}
            options={state.localProfiles.map((label, i) => ({
              id: String(i),
              label,
            }))}
            onChange={(v) => void run("selectLocalProfile", Number(v))}
          />
        </Row>
        <Row title={t("Processamento")}>
          <Picker
            label={t("Processamento")}
            disabled={state.localAsrBusy || state.localBenchmarkBusy}
            value={String(state.localDeviceIndex)}
            options={state.localDevices.map((label, i) => ({
              id: String(i),
              label,
            }))}
            onChange={(v) => void run("selectLocalDevice", Number(v))}
          />
        </Row>
        <div className="installation">
          <div>
            <div className="installation-status">
              {state.localAsrStatus === "installed" ? (
                <>
                  <Check size={17} />{t("Pronto para usar")}</>
              ) : state.localAsrBusy ? (
                <>
                  <LoaderCircle size={17} className="spin" />{t("Preparando modelo…")}</>
              ) : (
                t("Instalação do modelo")
              )}
            </div>
            <p className="hint">{t(state.localAsrDetail)}</p>
          </div>
          {state.localAsrBusy ? (
            <Button onClick={() => void run("cancelLocalAsr")}>{t("Cancelar")}</Button>
          ) : state.localAsrStatus !== "installed" &&
            state.localAsrCanInstall ? (
            <Button onClick={() => void run("installLocalAsr")}>
              <Download size={16} />{t("Instalar")}</Button>
          ) : (
            <Button onClick={() => void run("refreshLocalAsr")}>{t("Verificar")}</Button>
          )}
        </div>
        {state.localAsrBusy && (
          <progress
            aria-label={t("Instalação do modelo")}
            max="1"
            value={
              state.localAsrProgress >= 0 ? state.localAsrProgress : undefined
            }
          />
        )}
        {requirements.length > 0 && (
          <details>
            <summary>{t("Requisitos do modelo")}</summary>
            <ul>
              {requirements.map((value) => (
                <li key={value}>{value}</li>
              ))}
            </ul>
          </details>
        )}
        <details>
          <summary>{t("Opções do modelo local")}</summary>
          <Toggle
            title={t("Reconhecer durante a gravação (experimental)")}
            hint={t("Requer GPU NVIDIA. Pode reduzir a espera ao terminar com uma pausa, mas pode aumentar a espera em fala contínua. Mantém a gravação completa.")}
            checked={state.localStreaming}
            onChange={(v) => void run("setLocalStreaming", v)}
          />
          <p className="hint" role="status">
            {state.localBenchmarkDetail}
          </p>
          <div className="inline-actions">
            <Button
              disabled={state.localAsrBusy}
              onClick={() =>
                void run(
                  state.localBenchmarkBusy
                    ? "cancelLocalMeasurement"
                    : "installLocalAsr",
                )
              }
            >
              {state.localBenchmarkBusy
                ? t("Cancelar medição")
                : "Otimizar CPU/GPU"}
            </Button>
            {state.localAsrStatus === "installed" && (
              <>
                <Button
                  disabled={state.localAsrBusy || state.localBenchmarkBusy}
                  onClick={() => void useLocalModel()}
                >{t("Usar este modelo")}</Button>
                <Button
                  variant="ghost"
                  disabled={state.localAsrBusy || state.localBenchmarkBusy}
                  onClick={() => setConfirmAction("removeLocalAsr")}
                >{t("Remover modelo")}</Button>
              </>
            )}
          </div>
        </details>
      </Section>
      <Section
        title={
          <>{t("Serviços na nuvem")}<span className="badge">{t("Sua chave de API")}</span>
          </>
        }
      >
        <Row title={t("Serviço")}>
          <Picker
            label={t("Serviço na nuvem")}
            value={state.selectedProviderId}
            options={state.providers.filter((p) => p.id !== "local_asr")}
            onChange={(value) => void selectProvider(value)}
          />
        </Row>
        {state.selectedProviderId !== "local_asr" && (
          <>
            <Field
              title={t("Chave de API")}
              hint={
                state.providerHasApiKey
                  ? t("Uma chave já está salva. Preencha apenas para substituí-la.")
                  : t("A chave fica no armazenamento seguro do Clarify.")
              }
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={
                state.providerHasApiKey ? "••••••••••••••••" : t("Cole sua chave")
              }
            />
            {state.providerSupportsCustomEndpoint && (
              <details>
                <summary>{t("Endereço personalizado")}</summary>
                <Input
                  aria-label={t("Endpoint")}
                  value={endpoint}
                  onChange={(e) => setEndpoint(e.target.value)}
                />
              </details>
            )}
            <div className="service-actions">
              <span className="hint" role="status">
                {(state.providerError && t(state.providerError)) ||
                  (state.providerHasApiKey
                    ? t("Chave configurada")
                    : t("Sem chave configurada"))}
              </span>
              <Button
                disabled={state.providerBusy || busy}
                onClick={() => void validateProvider()}
              >
                {state.providerBusy ? t("Validando…") : t("Validar e salvar chave")}
              </Button>
            </div>
            {state.providerHasApiKey && (
              <Button
                variant="text"
                disabled={state.providerBusy}
                onClick={() => setConfirmAction("clearProvider")}
              >{t("Remover chave salva")}</Button>
            )}
          </>
        )}
      </Section>
    </>
  );
}
