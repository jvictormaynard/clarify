import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import {
  Button,
  Field,
  Input,
  Picker,
  Row,
  Section,
  SettingsDisclosure,
  Toggle,
} from "../components/ui";
import { Check, LoaderCircle, Download } from "lucide-react";
import { ChatGPTPlan } from "../components/chatgpt-plan";
import { profileName } from "../settings/use-text-profile-editor";

export function ModelsPage({ controller }: SettingsPageProps) {
  const {
    state,
    run,
    setConfirmAction,
    apiKey,
    setApiKey,
    endpoint,
    setEndpoint,
    validatingProvider,
    selectingProvider,
    selectProvider,
    validateProvider,
    useLocalModel,
  } = controller;
  const requirements = [
    ...new Set(state.localAsrRequirementsList.filter(Boolean)),
  ];
  const cloudSection = (
      <Section
        key="cloud-services" id="cloud-services"
        title={
          <>{t("Serviços na nuvem")}<span className="badge">{t(state.selectedProviderId === "chatgpt" ? "Seu plano ChatGPT" : "Sua chave de API")}</span>
          </>
        }
      >
        <Row title={t("Serviço")}>
          <Picker
            label={t("Serviço na nuvem")}
            disabled={selectingProvider}
            value={state.selectedProviderId}
            options={state.providers.filter((p) => p.id !== "local_asr")}
            onChange={(value) => void selectProvider(value)}
          />
        </Row>
        {state.selectedProviderId === "chatgpt" ? <ChatGPTPlan controller={controller} /> : state.selectedProviderId !== "local_asr" && (
          <>
            <Field
              title={t("Chave de API")}
              hint={
                state.providerHasApiKey
                  ? t("Uma chave já está salva. Preencha apenas para substituí-la.")
                  : t("A chave fica no armazenamento seguro do Clarify.")
              }
              disabled={selectingProvider}
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={
                state.providerHasApiKey ? "••••••••••••••••" : t("Cole sua chave")
              }
            />
            {state.providerSupportsCustomEndpoint && (
              <SettingsDisclosure title={t("Endereço personalizado")}>
                <Input
                  aria-label={t("Endpoint")}
                  disabled={selectingProvider}
                  value={endpoint}
                  onChange={(e) => setEndpoint(e.target.value)}
                />
              </SettingsDisclosure>
            )}
            <div className="service-actions">
              <span className="hint" role="status">
                {(state.providerError && t(state.providerError)) ||
                  (state.providerHasApiKey
                    ? t("Chave configurada")
                    : t("Sem chave configurada"))}
              </span>
              <Button
                disabled={state.providerBusy || validatingProvider || selectingProvider}
                onClick={() => void validateProvider()}
              >
                {state.providerBusy ? t("Validando…") : t("Validar e salvar chave")}
              </Button>
            </div>
            {state.providerHasApiKey && (
              <Button
                variant="text"
                disabled={state.providerBusy}
                onClick={() => setConfirmAction("clearProvider", state.selectedProviderId)}
              >{t("Remover chave salva")}</Button>
            )}
          </>
        )}
      </Section>
  );
  const localSection = (
      <Section
        key="local-models" id="local-models"
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
          <div className="inline-actions">
            {state.localAsrStatus === "installed" && (
              <Button
                variant="primary"
                disabled={state.localAsrBusy || state.localBenchmarkBusy}
                onClick={() => void useLocalModel()}
              >{t("Usar este modelo")}</Button>
            )}
            {state.localAsrBusy ? (
              <Button onClick={() => void run("cancelLocalAsr")}>{t("Cancelar")}</Button>
            ) : state.localAsrStatus !== "installed" &&
              state.localAsrCanInstall ? (
              <Button variant="primary" onClick={() => void run("installLocalAsr")}>
                <Download size={16} />{t("Instalar")}</Button>
            ) : (
              <Button onClick={() => void run("refreshLocalAsr")}>{t("Verificar")}</Button>
            )}
          </div>
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
          <SettingsDisclosure title={t("Requisitos do modelo")}>
            <ul>
              {requirements.map((value) => (
                <li key={value}>{value}</li>
              ))}
            </ul>
          </SettingsDisclosure>
        )}
        <SettingsDisclosure title={t("Opções do modelo local")}>
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
              <Button
                variant="ghost"
                disabled={state.localAsrBusy || state.localBenchmarkBusy}
                onClick={() => setConfirmAction("removeLocalAsr", undefined, state)}
              >{t("Remover modelo")}</Button>
            )}
          </div>
        </SettingsDisclosure>
      </Section>
  );
  const localFirst = state.selectedScope === "transcription" && state.routeProviderId === "local_asr";
  return <>{localFirst ? localSection : cloudSection}{localFirst ? cloudSection : localSection}
    <Section title={t("Processamento de texto")}>
      <p className="hint">{t("As ações usam estes perfis. Alterar um perfil não altera suas instruções.")}</p>
      {(state.textActionProfiles ?? []).filter(profile => !profile.managed).map(profile => <Row key={profile.id}
        title={profileName(profile.id)} hint={`${state.textActionProviders?.find(provider => provider.id === profile.providerId)?.label ?? profile.providerId} · ${profile.modelId || t("Sem modelo")}`}>
        <Button aria-label={t("Editar perfil de {name}", { name: profileName(profile.id) })}
          onClick={() => controller.textProfileEditor.open(profile)}>{t("Editar perfil")}</Button>
      </Row>)}
    </Section>
  </>;
}
