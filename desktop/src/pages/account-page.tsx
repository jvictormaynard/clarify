import { t } from "../i18n";
import { useRef, useState } from "react";
import { LogIn, RefreshCw, UserRound } from "lucide-react";
import { Button, Confirm, Field, Section, SettingsDisclosure } from "../components/ui";

import type { SettingsPageProps } from "../settings/use-settings";
import { AccountSignIn } from "../components/account-sign-in";

export function AccountPage({ controller }: SettingsPageProps) {
  const { state, run, dirty, accountPending } = controller;
  const account = state.accountState;
  const [server, setServer] = useState(account?.endpoint || "");
  const [confirmation, setConfirmation] = useState<"logout" | "delete" | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const accountBusy = !!account?.busy || accountPending;
  const command = (action: string, value = "") => {
    if (action === "cancel-social" ? account?.socialPending && !accountPending : !accountBusy && !dirty) void run("accountCommand", action, value);
  };
  if (!account) return null;
  const confirm = async () => {
    if (accountBusy || dirty || !confirmation || submittingRef.current) return;
    submittingRef.current = true;
    setSubmitting(true);
    try {
      if (await run("accountCommand", confirmation, "")) setConfirmation(null);
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };
  return <div className="account-page">
    <p className="hint account-intro">{t("A conta é opcional. Você pode continuar com sua chave ou com os modelos locais deste computador.")}</p>
    {account.error && <p role="alert" className="error">{t(account.error)}</p>}
    {account.syncError && <p role="alert" className="error">{t(account.syncError)}</p>}
    <fieldset className="account-sections" disabled={accountBusy || dirty}>
      {!account.signedIn ? <Section className="account-card account-auth" title={<><LogIn size={16} aria-hidden="true" />{t("Entrar ou criar conta")}</>}>
        {!account.endpoint && <p className="hint">{t("O serviço ainda não está configurado nesta versão. Os modos locais e com chave própria continuam disponíveis.")}</p>}
        <AccountSignIn account={account} command={command} busy={accountBusy}
          onContinueWithoutAccount={() => {
            if (accountBusy || dirty) return;
            if (account.managed) command("logout");
            void controller.navigate("dictation");
          }} />
        <SettingsDisclosure className="account-server" title={t("Servidor próprio")}>
          <div className="account-server-fields">
            <Field title={t("Endereço do servidor")} value={server} placeholder="https://…" onChange={e => setServer(e.target.value)} />
            <Button onClick={() => command("configure", server)}>{t("Salvar servidor")}</Button>
          </div>
        </SettingsDisclosure>
      </Section> : <>
        <Section className="account-card" title={<><UserRound size={16} aria-hidden="true" /><span className="account-email">{account.email}</span></>}>
          <p className="hint">{t("setup_account_library")}</p>
        </Section>
        <Section className="account-card" title={<><RefreshCw size={16} aria-hidden="true" />{t("Dicionário e snippets")}</>}>
          <p className="hint">{t("Seu dicionário, snippets e novas transcrições da conta são sincronizados automaticamente. Atalhos e chaves permanecem neste computador.")}</p>
          {account.dictionaryConflict && <>
            <p className="hint">{t("A escolha abaixo se aplica somente às palavras ou snippets alterados nos dois dispositivos. As outras alterações serão combinadas.")}</p>
            <div className="account-conflict-actions">
              <Button onClick={() => command("sync-local")}>{t("Manter as versões deste computador")}</Button>
              <Button onClick={() => command("sync-remote")}>{t("Usar as versões da conta")}</Button>
            </div>
          </>}
        </Section>
        <SettingsDisclosure className="danger-zone" title={t("Zona de perigo")}>
          <Section title={t("Sessão")}>
            <p className="hint">{t("Ao sair, o Clarify volta ao dicionário e ao processamento locais. As palavras da conta ficam separadas por conta neste computador.")}</p>
            <Button onClick={() => setConfirmation("logout")}>{t("Sair da conta")}</Button>
          </Section>
          <Section title={t("Excluir conta")}>
            <p className="hint">{t("Excluir a conta remove o dicionário, os snippets e o histórico compartilhados e o acesso ao serviço. Esta ação não pode ser desfeita. Os registros locais serão mantidos.")}</p>
            <Button className="destructive" onClick={() => setConfirmation("delete")}>{t("Excluir conta")}</Button>
          </Section>
        </SettingsDisclosure>
      </>}
    </fieldset>
    {account.socialPending && <Button variant="text" disabled={accountPending} onClick={() => command("cancel-social")}>{t("Cancelar login")}</Button>}
    <Confirm open={!!confirmation} onOpenChange={open => { if (!open && !submittingRef.current) setConfirmation(null); }}
      title={t(confirmation === "delete" ? "Excluir conta" : "Sair da conta")}
      description={t(confirmation === "delete"
        ? "Excluir a conta remove o dicionário, os snippets e o histórico compartilhados e o acesso ao serviço. Esta ação não pode ser desfeita. Os registros locais serão mantidos."
        : "Ao sair, o Clarify volta ao dicionário e ao processamento locais. As palavras da conta ficam separadas por conta neste computador.")}>
      <Button autoFocus disabled={submitting} onClick={() => { if (!submittingRef.current) setConfirmation(null); }}>{t("Cancelar")}</Button>
      <Button className={confirmation === "delete" ? "destructive" : ""} disabled={submitting || accountBusy || dirty}
        onClick={() => void confirm()}>{t(confirmation === "delete" ? "Confirmar exclusão da conta" : "Sair da conta")}</Button>
    </Confirm>
  </div>;
}
