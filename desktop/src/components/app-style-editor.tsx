import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import type { WritingStyle } from "../settings/bridge";
import { applicationName } from "../settings/use-app-style-editor";
import { Button, Field, Picker, Row, Section, SettingsDisclosure } from "./ui";
import { Dialog, DialogPopup, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "./primitives/dialog";

const descriptions: Record<WritingStyle, string> = {
  formal: "Usa linguagem profissional e frases completas, sem acrescentar informações.",
  casual: "Usa linguagem natural e conversacional, mantendo o sentido do texto.",
  very_casual: "Usa linguagem descontraída e direta, sem inventar gírias ou emojis.",
  natural: "Mantém seu vocabulário e tom, com frases naturais.",
  informal: "Usa linguagem cotidiana, sem acrescentar gírias ou emojis.",
  organized: "Organiza os pontos em parágrafos e as enumerações em listas, sem acrescentar conteúdo.",
};

export function AppStyleEditor({ controller: c }: SettingsPageProps) {
  const a = c.appStyleEditor, editor = a.editor;
  return <Dialog open={!!editor} onOpenChange={open => { if (!open) a.close(); }}>
    <DialogPopup bottomStickOnMobile={false} className="app-style-editor max-w-xl">
      <DialogHeader><DialogTitle>{t("Estilo do aplicativo")}</DialogTitle>
        <DialogDescription>{t("Escolha como o texto do ditado deve sair neste aplicativo.")}</DialogDescription>
      </DialogHeader>
      {editor && <div className="text-action-editor-content">
        {a.error && <p role="alert" className="error">{t(a.error)}</p>}
        <Section title={applicationName(editor.executable) || t("Aplicativo")}>
          {editor.isNew && <div className="inline-actions"><Button disabled={!c.state.applicationStyleTarget}
            onClick={() => a.change({ executable: c.state.applicationStyleTarget ?? "" })}>{t("Usar último aplicativo")}</Button></div>}
          <Row title={t("Estilo de escrita")} hint={t(descriptions[editor.style])}>
            <Picker label={t("Estilo de escrita")} value={editor.style}
              options={[
                { id: "formal", label: t("Formal") }, { id: "casual", label: t("Casual") }, { id: "very_casual", label: t("Muito casual") },
                ...(["natural", "informal", "organized"].includes(editor.style) ? [{ id: editor.style, label: t(({ natural: "Natural", informal: "Informal", organized: "Organizado" } as Record<string, string>)[editor.style]) }] : []),
              ]}
              onChange={style => a.change({ style: style as WritingStyle })} />
          </Row>
          <SettingsDisclosure title={editor.isNew ? t("Escolher outro aplicativo") : t("Detalhes do aplicativo")} defaultOpen={!editor.executable}>
            <Field title={t("Caminho do aplicativo")} value={editor.executable} readOnly={!editor.isNew}
              onChange={event => a.change({ executable: event.target.value })}
              hint={t("Informe o caminho completo do arquivo .exe. O arquivo não será aberto nem executado.")} />
          </SettingsDisclosure>
        </Section>
      </div>}
      <DialogFooter>
        {a.discardRequested && <span className="settings-dialog-unsaved" role="status">{t("Descartar as alterações desta regra?")}</span>}
        {a.discardRequested && <Button variant="ghost" onClick={() => a.setDiscardRequested(false)}>{t("Continuar editando")}</Button>}
        <Button variant="ghost" disabled={a.saving} onClick={() => a.close(true)}>{a.discardRequested ? t("Descartar") : t("Cancelar")}</Button>
        <Button variant="primary" loading={a.saving} disabled={!editor?.executable.trim() || (!editor.isNew && !a.dirty)}
          onClick={() => void a.save()}>{t("Salvar regra")}</Button>
      </DialogFooter>
    </DialogPopup>
  </Dialog>;
}
