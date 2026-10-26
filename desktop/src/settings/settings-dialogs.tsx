import { t } from "../i18n";
import { Button, Confirm, Input } from "../components/ui";
import type { SettingsController } from "./use-settings";

const confirmations = {
  clearProvider: {
    title: t("Remover chave salva?"),
    description:
      t("A chave será removida do armazenamento seguro agora. Será necessário adicioná-la novamente para usar este serviço."),
  },
  removeLocalAsr: {
    title: t("Remover modelo local?"),
    description:
      t("Os arquivos deste modelo serão removidos agora. Para usá-lo novamente, será necessário reinstalá-lo."),
  },
  resetAllHotkeys: {
    title: t("Restaurar atalhos?"),
    description:
      t("Os atalhos voltarão ao padrão e serão salvos agora."),
  },
};

export function SettingsDialogs({
  controller: c,
}: {
  controller: SettingsController;
}) {
  const confirmation = c.confirmAction
    ? confirmations[c.confirmAction]
    : confirmations.resetAllHotkeys;
  const waitingForDraftRoute = !c.closing && c.routeLoading && (c.page === "dictation" || c.page === "text");
  return (
    <>
      <Confirm
        open={c.confirmAction !== null}
        onOpenChange={(open) => {
          if (!open) c.setConfirmAction(null);
        }}
        {...confirmation}
      >
        <Button
          variant="ghost"
          disabled={c.confirming}
          onClick={() => c.setConfirmAction(null)}
        >{t("Cancelar")}</Button>
        <Button disabled={c.confirming} onClick={() => void c.confirmMutation()}>{t("Confirmar")}</Button>
      </Confirm>
      <Confirm
        open={(c.closing && c.dirty) || c.discarding}
        onOpenChange={(open) => {
          if (!open) c.cancelDiscard();
        }}
        title={t("Alterações não salvas")}
        description={t(c.closing
          ? "Salve ou descarte as alterações de todas as páginas para fechar."
          : "Salve suas alterações ou descarte-as para continuar.")}
      >
        <Button variant="ghost" onClick={c.cancelDiscard}>{t("Continuar editando")}</Button>
        <Button disabled={c.saving || c.discardingDrafts || waitingForDraftRoute} onClick={() => void c.discardAndClose()}>{t(c.closing ? "Descartar tudo" : "Descartar")}</Button>
        <Button
          variant="primary"
          disabled={c.saving || c.discardingDrafts || c.validatingProvider || waitingForDraftRoute}
          onClick={() => void c.saveAndClose()}
        >{t(c.closing ? "Salvar tudo" : "Salvar")}</Button>
      </Confirm>
      <Confirm
        open={!!c.capture}
        onOpenChange={(open) => {
          if (!open) c.setCapture(undefined);
        }}
        title={t("Definir atalho")}
        description={t("Clique no campo e pressione a combinação desejada.")}
      >
        <Input
          aria-label={t("Novo atalho")}
          placeholder={t("Pressione as teclas…")}
          autoFocus
          readOnly
          onKeyDown={(event) => void c.captureHotkey(event)}
          onKeyUp={(event) => void c.captureHotkey(event)}
          onMouseDown={(event) => { if ([3, 4].includes(event.button)) event.preventDefault(); }}
          onMouseUp={(event) => void c.captureMouseHotkey(event)}
          onAuxClick={(event) => event.preventDefault()}
        />
      </Confirm>
    </>
  );
}
