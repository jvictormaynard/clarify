import { ShortcutButton } from "./shortcut-button";
import { useId } from "react";
import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import type { TextActionKind } from "../settings/bridge";
import { Button, Confirm, Field, Input, Picker, Row, Section, SettingsDisclosure, TextArea, Toggle } from "./ui";
import { Dialog, DialogPopup, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "./primitives/dialog";
import { actionDisplayName } from "../settings/display-labels";
import { textActionLanguages } from "./after-dictation-action";
import { profileName } from "../settings/display-labels";

export function TextActionEditor({ controller: c }: SettingsPageProps) {
  const a = c.textActions, editor = a.editor;
  const promptId = useId(), sampleId = useId();
  const profiles = c.state.textActionProfiles ?? [];
  const profile = profiles.find(item => item.id === editor?.action.processingProfileId);
  const unavailable = !profile || !profile.enabled || !profile.available || !editor?.action.enabled;
  const contextChanged = !!editor && editor.context !== c.state.textActionContext;
  return <>
    <Dialog open={!!editor} onOpenChange={open => { if (!open) void a.close(); }}>
      <DialogPopup className="text-action-editor max-w-4xl" bottomStickOnMobile={false} finalFocus={a.opener}>
        <DialogHeader><DialogTitle>{a.using && editor ? `${t("Usar ação")}: ${actionDisplayName(editor.action)}` : editor?.isNew ? t("Nova ação") : t("Editar ação")}</DialogTitle>
          {!a.using && <DialogDescription>{t("Defina as instruções e, se quiser, um atalho para esta ação.")}</DialogDescription>}
        </DialogHeader>
        {editor && <div className="text-action-editor-content">
          {(a.error || contextChanged) && <p className="error" role="alert">{t(a.error || "A conta ou o servidor mudou. Copie suas instruções antes de fechar este editor.")}</p>}
          {!a.using && <div className="inline-actions"><Button disabled={a.saving || a.capturing || a.captureStarting || contextChanged} loading={a.refreshing}
            onClick={() => void a.refresh()}>{t("Atualizar ações")}</Button></div>}
          {c.state.textActionMutation?.restoreRequired && <p className="hint" role="status">{t("Atualize as ações para concluir a recuperação. Seu rascunho será mantido.")}</p>}
          <div className="page-content">
            {!a.using && <>
            {a.conflict && <Section title={t("A versão salva mudou")} grouped={false}>
              <p className="hint" role="status">{a.conflict.action ? t("Compare a versão salva antes de manter seu rascunho. Nada será substituído sem salvar.") : t("Esta ação foi excluída. Você pode salvar seu rascunho como uma nova ação.")}</p>
              {a.conflict.action && <><p>{a.conflict.action.name}</p><TextArea aria-label={t("Instruções da versão salva")} readOnly value={a.conflict.action.prompt} /></>}
              <div className="inline-actions">{a.conflict.action && <Button onClick={() => a.resolveConflict(true)}>{t("Usar versão salva")}</Button>}
                <Button onClick={() => a.resolveConflict(false)}>{a.conflict.action ? t("Manter meu rascunho") : t("Salvar rascunho como nova ação")}</Button></div>
            </Section>}
            <Section title={t("Ação de texto")}>
              <Field title={t("Nome da ação")} value={actionDisplayName(editor.action)} maxLength={80} autoFocus
                onChange={event => a.change({ name: event.target.value })} placeholder={t("Ex.: Resumir em tópicos")} />
              <Toggle title={t("Ativar ação")} checked={editor.action.enabled} onChange={enabled => a.change({ enabled })} />
              <Row title={t("Atalho")} hint={t("O atalho só será aplicado quando você salvar.")}>
                {a.capturing ? <Input aria-label={t("Novo atalho da ação")} placeholder={t("Pressione as teclas…")} readOnly autoFocus
                  onKeyDownCapture={a.captureKey} onKeyUp={a.captureKey}
                  onMouseDown={event => { if ([3, 4].includes(event.button)) event.preventDefault(); }}
                  onMouseUp={a.captureMouse} onAuxClick={event => event.preventDefault()} />
                  : <ShortcutButton shortcut={editor.action.shortcut} disabled={a.captureStarting || a.refreshing} onClick={() => void a.beginCapture()} />}
                {a.capturing ? <Button variant="ghost" onClick={() => void a.cancelCapture()}>{t("Cancelar captura")}</Button>
                  : editor.action.shortcut && <Button variant="ghost" onClick={() => a.change({ shortcut: null })}>{t("Remover atalho")}</Button>}
              </Row>
              <SettingsDisclosure title={t("Advanced")}>
                <Row title={t("Tipo de ação")}><Picker label={t("Tipo de ação")} value={editor.action.kind}
                  options={[{ id: "custom", label: t("Personalizada") }, { id: "rewrite", label: t("Reescrita") }, { id: "translation", label: t("Tradução") }]}
                  onChange={kind => a.change({ kind: kind as TextActionKind })} /></Row>
                <Row title={t("Perfil de processamento")} hint={t("Use o serviço de texto configurado ou escolha um perfil específico.")}>
                  <Picker label={t("Perfil de processamento")} value={editor.action.processingProfileId}
                    options={[{ id: "default", label: t("Padrão do texto") }, ...profiles.filter(profile => profile.id !== "default").map(profile => ({ id: profile.id, label: profile.managed ? t("Conta Clarify") : profileName(profile.id) }))]}
                    onChange={processingProfileId => a.change({ processingProfileId })} />
                </Row>
              </SettingsDisclosure>
            </Section>
            <Section title={t("Instruções")} grouped={false}>
              <label className="sr-only" htmlFor={promptId}>{t("Instruções da ação")}</label>
              <TextArea id={promptId} aria-describedby={`${promptId}-hint`} className="prompt min-h-48" value={editor.action.prompt}
                onChange={event => a.change({ prompt: event.target.value })} placeholder={t("Descreva o que deve mudar no texto e o que deve ser preservado.")} />
              <p id={`${promptId}-hint`} className="hint">{t("Até 8 KiB. O texto será tratado como conteúdo da ação.")}</p>
            </Section>
            </>}
            <Section title={a.using ? t("Texto de entrada") : t("Testar ação")} grouped={false}>
              {a.using && <>
                {unavailable && <p className="error" role="status">{t("A ação ou o serviço de texto não está disponível. Verifique a configuração.")}</p>}
                {unavailable && <Button onClick={async () => { if (await a.close(true)) await c.navigate(c.state.accountState?.managed || c.state.accountState?.signedIn ? "account" : "models"); }}>{t("Configurar processamento")}</Button>}</>}
              <label className="sr-only" htmlFor={sampleId}>{a.using ? t("Texto de entrada") : t("Texto de exemplo")}</label>
              <TextArea id={sampleId} className="min-h-24" autoFocus={a.using} value={a.sample} onChange={event => a.setSample(event.target.value)}
                placeholder={a.using ? t("Cole o texto que você quer transformar.") : t("Cole um texto de exemplo.")} />
              <Row title={t("Idioma de saída")}><Picker label={t("Idioma de saída")}
                value={a.sampleLanguage} options={[{ id: "auto", label: t("Idioma original") }, ...textActionLanguages]} onChange={a.setSampleLanguage} /></Row>
              <div className="inline-actions"><Button loading={a.previewing} variant={a.using ? "primary" : "default"} disabled={(a.using && unavailable) || editor.isNew || a.dirty || a.refreshing || !!a.conflict || !a.sample.trim() || contextChanged} onClick={() => void a.test()}>{a.using ? t("Executar ação") : t("Test")}</Button>
                {a.previewing && <Button onClick={a.cancelPreview}>{t("Cancelar")}</Button>}</div>
              {a.dirty && <p className="hint">{t("Salve a ação para testar as instruções.")}</p>}
              {a.preview && <div className="text-action-preview" role="status"><h3>{t("Resultado")}</h3>{a.using ? <TextArea aria-label={t("Resultado")} readOnly value={a.preview} /> : <p>{a.preview}</p>}{a.using && <Button disabled={a.copying || contextChanged} loading={a.copying} onClick={() => void a.copyPreview()}>{t(a.copied ? "Copiado." : "Copiar resultado")}</Button>}</div>}
            </Section>
          </div>
        </div>}
        <DialogFooter>
          {a.discardRequested && <span className="settings-dialog-unsaved" role="status">{t("Descartar as alterações desta ação?")}</span>}
          {a.discardRequested && <Button variant="ghost" onClick={() => a.setDiscardRequested(false)}>{t("Continuar editando")}</Button>}
          <Button variant="ghost" disabled={a.saving} onClick={() => void a.close(true)}>{a.discardRequested ? t("Descartar") : a.dirty ? t("Cancelar") : t("Concluído")}</Button>
          {!a.using && <Button variant="primary" disabled={!a.dirty || a.saving || a.refreshing || !!a.conflict || a.capturing || a.captureStarting || contextChanged}
            onClick={() => void a.save(a.discardRequested)}>{a.saving ? t("Salvando…") : t("Salvar ação")}</Button>}
        </DialogFooter>
      </DialogPopup>
    </Dialog>
    <Confirm open={!!a.deleting} onOpenChange={open => { if (!open) a.cancelDelete(); }} title={t("Excluir ação?")}
      error={a.error}
      description={t("A ação e seu atalho serão removidos. Os textos do histórico serão mantidos.")}>
      <Button variant="ghost" disabled={a.saving} onClick={a.cancelDelete}>{t("Cancelar")}</Button>
      {a.error && <Button disabled={a.saving} loading={a.refreshing} onClick={() => void a.refresh()}>{t("Atualizar ações")}</Button>}
      <Button disabled={a.saving || a.refreshing} onClick={() => void a.confirmDelete()}>{t("Excluir")}</Button>
    </Confirm>
  </>;
}
