import { t } from "../i18n";
import { useState } from "react";
import { Button, Field, Section } from "../components/ui";
import type { SettingsPageProps } from "../settings/use-settings";
import { AccountSignIn } from "../components/account-sign-in";

export function AccountPage({ controller }: SettingsPageProps) {
  const { state, run, dirty, busy } = controller;
  const account = state.accountState;
  const [server, setServer] = useState(account?.endpoint || "");
  const [deleting, setDeleting] = useState(false);
  const command = (action: string, value = "") => void run("accountCommand", action, value);
  if (!account) return null;
  const used = Math.ceil(((account.usage.used_ms || 0) + (account.usage.reserved_ms || 0)) / 60000);
  const limit = Math.floor((account.usage.limit_ms || 0) / 60000);
  return <>
    <p className="hint">{t("A conta é opcional. Você pode continuar com sua chave ou com os modelos locais deste computador.")}</p>
    {account.error && <p role="alert" className="error">{t(account.error)}</p>}
    {account.syncError && <p role="alert" className="error">{t(account.syncError)}</p>}
    <fieldset disabled={account.busy || dirty}>
      {!account.signedIn ? <Section title={t("Entrar ou criar conta")}>
        {!account.endpoint && <p className="hint">{t("O serviço ainda não está configurado nesta versão. Os modos locais e com chave própria continuam disponíveis.")}</p>}
        <AccountSignIn account={account} command={command} busy={busy || account.busy} />
        {account.managed && !account.pending && <Button variant="text" onClick={() => command("logout")}>{t("Continuar sem conta")}</Button>}
        <details><summary>{t("Servidor próprio")}</summary>
          <Field title={t("Endereço do servidor")} value={server} placeholder="https://…" onChange={e => setServer(e.target.value)} />
          <Button onClick={() => command("configure", server)}>{t("Salvar servidor")}</Button>
        </details>
      </Section> : <>
        <Section title={account.email}>
          <p className="hint">{t("O Clarify gerencia os modelos e provedores da sua conta. Áudio, texto e palavras ativas do dicionário são processados pelo Clarify.")}</p>
          {!account.hosted && <Button loading={busy} onClick={() => command("hosted", "1")}>{t("Ativar processamento do Clarify")}</Button>}
          <p>{t("{v0} de {v1} minutos neste mês", { v0: used, v1: limit })}</p>
          <p className="hint">{t("Cota compartilhada entre desktop e iPhone. Atualizada após cada processamento.")}</p>
          {account.usage.hosted_available === false && <p className="hint">{t("O processamento gratuito está indisponível no momento.")}</p>}
        </Section>
        <Section title={t("Dicionário compartilhado")}>
          <p className="hint">{t("Suas palavras são sincronizadas automaticamente. Atalhos, chaves e histórico permanecem neste computador.")}</p>
          {account.dictionaryConflict && <>
            <p className="hint">{t("A escolha abaixo se aplica somente às palavras alteradas nos dois dispositivos. As outras alterações serão combinadas.")}</p>
            <Button onClick={() => command("sync-local")}>{t("Manter as versões deste computador")}</Button>
            <Button onClick={() => command("sync-remote")}>{t("Usar as versões da conta")}</Button>
          </>}
        </Section>
        <Section title={t("Sessão")}>
          <p className="hint">{t("Ao sair, o Clarify volta ao dicionário e ao processamento locais. As palavras da conta ficam separadas por conta neste computador.")}</p>
          <Button onClick={() => command("logout")}>{t("Sair da conta")}</Button>
          {!deleting ? <Button onClick={() => setDeleting(true)}>{t("Excluir conta…")}</Button> : <>
            <p className="error">{t("Excluir a conta remove seu dicionário compartilhado e o acesso ao serviço. Esta ação não pode ser desfeita. O histórico local será mantido.")}</p>
            <Button onClick={() => command("delete")}>{t("Confirmar exclusão da conta")}</Button>
            <Button onClick={() => setDeleting(false)}>{t("Cancelar")}</Button>
          </>}
        </Section>
      </>}
    </fieldset>
  </>;
}
