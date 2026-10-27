import { useEffect, useRef, useState } from "react";
import { t } from "../i18n";
import { Button, Field } from "./ui";
import { Dialog, DialogDescription, DialogFooter, DialogHeader, DialogPopup, DialogTitle } from "./primitives/dialog";
import { type HistoryCorrectionReply, type HistoryEntry, type HistoryScope } from "../settings/bridge";
import type { SettingsPageProps } from "../settings/use-settings";

export function HistoryCorrectionAction({ entry, scope, controller }: {
  entry: HistoryEntry; scope: HistoryScope; controller: SettingsPageProps["controller"];
}) {
  const { state } = controller;
  const historyCorrection = controller.runHistoryCorrection;
  const [open, setOpen] = useState(false);
  const [heard, setHeard] = useState("");
  const [corrected, setCorrected] = useState("");
  const [proposal, setProposal] = useState<HistoryCorrectionReply | null>(null);
  const [receipt, setReceipt] = useState("");
  const [canUndo, setCanUndo] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const busy = useRef(false);
  const generation = useRef(0);
  const proposalToken = useRef("");
  const current = useRef({ context: scope.context, revision: scope.revision, library: state.snippetContext });
  current.current = { context: state.historyState?.context || "", revision: state.historyState?.revision || "", library: state.snippetContext };
  const active = (request: number) => generation.current === request && current.current.context === scope.context && current.current.revision === scope.revision && current.current.library === state.snippetContext;
  useEffect(() => {
    const request = ++generation.current;
    return () => {
      if (generation.current === request) generation.current++;
      if (proposalToken.current) void historyCorrection("cancel", { token: proposalToken.current });
    };
  }, [scope.context, scope.revision, state.snippetContext]);
  useEffect(() => {
    if (!receipt || !canUndo) return;
    let cancelled = false, checking = false;
    const request = generation.current;
    const check = async () => {
      if (checking) return;
      checking = true;
      try {
        const result = await historyCorrection("status", { token: receipt }, () => !cancelled && active(request));
        if (!cancelled && active(request) && result && !result.canUndo) setCanUndo(false);
      } catch { if (!cancelled && active(request)) setCanUndo(false); }
      finally { checking = false; }
    };
    const timer = window.setInterval(() => void check(), 400);
    void check();
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [receipt, canUndo, open, scope.context, scope.revision, state.snippetContext]);
  const discardProposal = () => {
    if (proposalToken.current) void historyCorrection("cancel", { token: proposalToken.current });
    proposalToken.current = ""; setProposal(null);
  };
  const changeOpen = (value: boolean) => {
    if (busy.current) return;
    if (!value) { generation.current++; discardProposal(); }
    setOpen(value); setError("");
  };
  const perform = async (action: "preview" | "confirm" | "undo") => {
    if (busy.current) return;
    const request = generation.current;
    if (!active(request)) return;
    busy.current = true; setPending(true); setError("");
    try {
      const payload: Record<string, string> = action === "preview" ? { ...scope, id: entry.id, libraryContext: state.snippetContext, heard, corrected }
        : { token: action === "undo" ? receipt : proposalToken.current };
      const result = await historyCorrection(action, payload, () => active(request));
      if (!active(request) || !result) return;
      if (result.error) {
        setError(t(result.error));
        if (action === "confirm") discardProposal();
        return;
      }
      if (action === "preview") {
        proposalToken.current = result.token || "";
        setProposal(result);
      } else if (action === "confirm") {
        proposalToken.current = ""; setProposal(null); setOpen(false);
        setReceipt(result.receipt || ""); setCanUndo(!!result.canUndo);
        setNotice(t("Termo salvo no dicionário."));
      } else {
        setCanUndo(false);
        setNotice(t(result.status === "undone" ? "Adição desfeita." : "Desfazer indisponível: o dicionário ou a sessão mudou."));
        if (result.status === "undone") setReceipt("");
      }
    } catch { if (active(request)) setError(t("Não foi possível salvar a correção. Tente novamente.")); }
    finally { busy.current = false; if (active(request)) setPending(false); }
  };
  if (!entry.hasOriginal || (state.accountState?.managed && !state.accountState.signedIn)) return null;
  const matchingOwner = entry.owner === (state.accountState?.signedIn ? "account" : "local");
  return <>
    <Button variant="text" disabled={!matchingOwner} title={!matchingOwner ? t("O registro e o dicionário devem pertencer à mesma conta ou ao modo local.") : undefined} onClick={() => changeOpen(true)}>{t("Corrigir termo")}</Button>
    {notice && <span role="status" className="hint">{notice}</span>}
    {receipt && <span className="hint">
      <Button variant="text" disabled={!canUndo || pending} onClick={() => void perform("undo")}>{t("Desfazer adição")}</Button>
      {!canUndo && <span role="status">{t("Desfazer indisponível: o dicionário ou a sessão mudou.")}</span>}
    </span>}
    {!open && error && <span role="alert" className="error">{error}</span>}
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogPopup showCloseButton={!pending}>
        <DialogHeader>
          <DialogTitle>{t("Corrigir termo")}</DialogTitle>
          <DialogDescription>{t("Revise o termo ouvido e a grafia correta antes de salvar. O original permanece igual.")}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 px-6 pb-6">
          <Field title={t("Termo ouvido")} value={proposal?.heard ?? heard} maxLength={256} disabled={pending || !!proposal} onChange={event => setHeard(event.target.value)} />
          <Field title={t("Termo correto")} value={proposal?.entry?.term ?? corrected} maxLength={256} disabled={pending || !!proposal} onChange={event => setCorrected(event.target.value)} />
          {proposal?.status === "already_exists" ? <p role="status" className="hint">{t("Este termo já existe. Os dados existentes foram mantidos.")}</p>
            : proposal && !!proposal.entry?.aliases.length && <p className="hint">{t("O termo ouvido será salvo como alias. Aliases são dicas para futuras transcrições.")}</p>}
          {proposal && state.accountState?.signedIn && <p className="hint">{t("A sincronização começa em 5 segundos após salvar. Você pode desfazer enquanto o dicionário não mudar.")}</p>}
          {error && <p role="alert" className="error">{error}</p>}
        </div>
        <DialogFooter>
          <Button disabled={pending} onClick={() => changeOpen(false)}>{t("Cancelar")}</Button>
          {proposal ? <><Button disabled={pending} onClick={discardProposal}>{t("Editar")}</Button>
            <Button variant="primary" disabled={pending || proposal.status === "already_exists"} loading={pending} onClick={() => void perform("confirm")}>{t("Salvar no dicionário")}</Button></>
            : <Button variant="primary" disabled={pending || !heard.trim() || !corrected.trim()} loading={pending} onClick={() => void perform("preview")}>{t("Revisar correção")}</Button>}
        </DialogFooter>
      </DialogPopup>
    </Dialog>
  </>;
}
