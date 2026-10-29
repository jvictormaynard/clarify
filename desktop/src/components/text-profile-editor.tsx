import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { profileName } from "../settings/use-text-profile-editor";
import { Button, Field, Picker, Row, Section, SettingsDisclosure, Toggle } from "./ui";
import { Dialog, DialogPopup, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "./primitives/dialog";

export function TextProfileEditor({ controller: c }: SettingsPageProps) {
  const a = c.textProfileEditor, editor = a.editor;
  const providers = c.state.textActionProviders ?? [];
  const provider = providers.find(item => item.id === editor?.value.providerId);
  const modelOptions = [...a.models];
  if (editor?.value.modelId && !modelOptions.some(model => model.id === editor.value.modelId)) modelOptions.unshift({ id: editor.value.modelId, label: editor.value.modelId });
  const statusMessages: Partial<Record<typeof a.modelStatus, string>> = {
    not_configured: "Configure a chave ou conecte sua conta em Modelos e serviços.",
    account_mismatch: "Este perfil usa outra conta ChatGPT. Selecione a conta vinculada em Modelos e serviços.",
    refresh_required: "Atualize a lista para consultar o endereço informado.",
    stale: "A configuração mudou. Atualize os modelos antes de escolher outro.",
    empty: "Nenhum modelo disponível. Verifique o serviço.",
    error: "Não foi possível carregar os modelos. Atualize a lista para tentar novamente.",
  };
  const status = statusMessages[a.modelStatus];
  return <Dialog open={!!editor} onOpenChange={open => { if (!open) a.close(); }}>
    <DialogPopup className="app-style-editor max-w-xl" bottomStickOnMobile={false}>
      <DialogHeader><DialogTitle>{t("Perfil de processamento")}</DialogTitle>
        <DialogDescription>{t("Escolha o serviço e o modelo usados pelas ações deste perfil.")}</DialogDescription></DialogHeader>
      {editor && <div className="text-action-editor-content">
        {(a.error || editor.context !== c.state.textActionContext) && <p className="error" role="alert">{t(a.error || "A conta mudou. Abra o perfil novamente antes de salvar.")}</p>}
        <Section title={profileName(editor.value.id)}>
          <Toggle title={t("Ativar processamento")} checked={editor.value.enabled} onChange={enabled => a.change({ enabled })} />
          <Row title={t("Serviço")}><Picker label={t("Serviço do perfil")} value={editor.value.providerId} options={providers}
            onChange={providerId => a.change({ providerId, modelId: providers.find(item => item.id === providerId)?.defaultModel ?? "", customEndpoint: "" })} /></Row>
          <Row title={t("Modelo")}><Picker label={t("Modelo do perfil")} value={editor.value.modelId} options={modelOptions}
            busy={a.modelStatus === "loading"} onRefresh={() => void a.loadModels(true)}
            onChange={modelId => a.change({ modelId })} /></Row>
          {status && <p className="hint" role="status">{t(status)}</p>}
          {editor.value.providerId !== "chatgpt" && <SettingsDisclosure title={t("Modelo e endereço personalizados")}>
            <Field title={t("ID do modelo")} value={editor.value.modelId} onChange={event => a.change({ modelId: event.target.value })}
              hint={t("Opcional: use um modelo que não aparece no catálogo.")} />
            {provider?.supportsCustomEndpoint && <Field title={t("Endereço do perfil")} value={editor.value.customEndpoint}
              onChange={event => a.change({ customEndpoint: event.target.value })} hint={t("Deixe vazio para usar o endereço do serviço.")} />}
          </SettingsDisclosure>}
        </Section>
      </div>}
      <DialogFooter>
        {a.discardRequested && <span className="settings-dialog-unsaved" role="status">{t("Descartar as alterações deste perfil?")}</span>}
        {a.discardRequested && <Button variant="ghost" onClick={() => a.setDiscardRequested(false)}>{t("Continuar editando")}</Button>}
        <Button variant="ghost" disabled={a.saving} onClick={() => a.close(true)}>{a.discardRequested ? t("Descartar") : t("Cancelar")}</Button>
        <Button variant="primary" loading={a.saving} disabled={!a.dirty || !a.canSaveModel || editor?.context !== c.state.textActionContext}
          onClick={() => void a.save()}>{t("Salvar perfil")}</Button>
      </DialogFooter>
    </DialogPopup>
  </Dialog>;
}
