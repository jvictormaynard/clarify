import { Button, Confirm, Input } from "../components/ui";
import type { SettingsController } from "./use-settings";

const confirmations = {
  clearProvider: {
    title: "Remover chave salva?",
    description:
      "A chave será removida do armazenamento seguro agora. Será necessário adicioná-la novamente para usar este serviço.",
  },
  removeLocalAsr: {
    title: "Remover modelo local?",
    description:
      "Os arquivos deste modelo serão removidos agora. Para usá-lo novamente, será necessário reinstalá-lo.",
  },
  resetAllHotkeys: {
    title: "Restaurar atalhos?",
    description:
      "Os atalhos voltarão ao padrão. Use Salvar alterações para aplicar ou Descartar para manter os atalhos atuais.",
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
          disabled={c.busy}
          onClick={() => c.setConfirmAction(null)}
        >
          Cancelar
        </Button>
        <Button disabled={c.busy} onClick={() => void c.confirmMutation()}>
          Confirmar
        </Button>
      </Confirm>
      <Confirm
        open={(c.closing && c.dirty) || c.discarding}
        onOpenChange={(open) => {
          if (!open) c.cancelDiscard();
        }}
        title="Alterações não salvas"
        description="Salve suas alterações ou descarte-as para continuar."
      >
        <Button variant="ghost" disabled={c.busy} onClick={c.cancelDiscard}>
          Continuar editando
        </Button>
        <Button disabled={c.busy} onClick={() => void c.discardAndClose()}>
          Descartar
        </Button>
        <Button
          variant="primary"
          disabled={c.busy}
          onClick={() => void c.saveAndClose()}
        >
          Salvar
        </Button>
      </Confirm>
      <Confirm
        open={!!c.capture}
        onOpenChange={(open) => {
          if (!open) c.setCapture(undefined);
        }}
        title="Definir atalho"
        description="Clique no campo e pressione a combinação desejada."
      >
        <Input
          aria-label="Novo atalho"
          placeholder="Pressione as teclas…"
          autoFocus
          readOnly
          onKeyDown={(event) => void c.captureHotkey(event)}
        />
      </Confirm>
    </>
  );
}
