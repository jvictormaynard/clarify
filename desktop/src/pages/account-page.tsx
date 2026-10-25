import { t, uiLanguage } from "../i18n";
import { useState } from "react";
import { Button, Confirm, Field, Section } from "../components/ui";
import { usageProgress } from "../../../shared/usage";
import type { SettingsPageProps } from "../settings/use-settings";
import { AccountSignIn } from "../components/account-sign-in";

export function AccountPage({ controller }: SettingsPageProps) {
  const { state, run, dirty, busy } = controller;
  const account = state.accountState;
  const [server, setServer] = useState(account?.endpoint || "");
  const [confirmation, setConfirmation] = useState<"logout" | "delete" | null>(null);
  const command = (action: string, value = "") => void run("accountCommand", action, value);
  if (!account) return null;
  const usageLoaded = Number.isFinite(account.usage.used_ms) && Number.isFinite(account.usage.limit_ms);
  const usage = usageProgress(account.usage.used_ms, account.usage.limit_ms);
  const minutes = new Intl.NumberFormat(uiLanguage, { maximumFractionDigits: 1 });
  const usageLabel = t("{v0} de {v1} minutos neste mês", {
    v0: minutes.format(usage.usedMinutes), v1: minutes.format(usage.limitMinutes),
  });
  const confirm = async () => {
    if (confirmation && await run("accountCommand", confirmation, "")) setConfirmation(null);
  };
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
          {usageLoaded ? <>
            <p>{usageLabel}</p>
            <div className="usage-progress" role="progressbar" aria-label={t("Uso neste mês")}
              aria-valuemin={0} aria-valuemax={100} aria-valuenow={usage.percent} aria-valuetext={usageLabel}>
              <div style={{ width: `${usage.percent}%` }} />
            </div>
          </> : account.error ? <Button onClick={() => command("refresh")}>{t("Retry")}</Button>
            : <p role="status" className="hint">{t("Carregando…")}</p>}
          <p className="hint">{t("Cota compartilhada entre desktop e iPhone.")}</p>
          {account.usage.hosted_available === false && <p className="hint">{t("O processamento gratuito está indisponível no momento.")}</p>}
        </Section>
        <Section title={t("Dicionário e snippets")}>
          <p className="hint">{t("Seu dicionário, snippets e novas transcrições da conta são sincronizados automaticamente. Atalhos e chaves permanecem neste computador.")}</p>
          {account.dictionaryConflict && <>
            <p className="hint">{t("A escolha abaixo se aplica somente às palavras ou snippets alterados nos dois dispositivos. As outras alterações serão combinadas.")}</p>
            <Button onClick={() => command("sync-local")}>{t("Manter as versões deste computador")}</Button>
            <Button onClick={() => command("sync-remote")}>{t("Usar as versões da conta")}</Button>
          </>}
        </Section>
        <details className="danger-zone">
          <summary>{t("Zona de perigo")}</summary>
          <Section title={t("Sessão")}>
            <p className="hint">{t("Ao sair, o Clarify volta ao dicionário e ao processamento locais. As palavras da conta ficam separadas por conta neste computador.")}</p>
            <Button onClick={() => setConfirmation("logout")}>{t("Sair da conta")}</Button>
          </Section>
          <Section title={t("Excluir conta")}>
            <p className="hint">{t("Excluir a conta remove o dicionário, os snippets e o histórico compartilhados e o acesso ao serviço. Esta ação não pode ser desfeita. Os registros locais serão mantidos.")}</p>
            <Button className="destructive" onClick={() => setConfirmation("delete")}>{t("Excluir conta")}</Button>
          </Section>
        </details>
      </>}
    </fieldset>
    {account.socialPending && <Button variant="text" onClick={() => command("cancel-social")}>{t("Cancelar login")}</Button>}
    <Confirm open={!!confirmation} onOpenChange={open => { if (!open) setConfirmation(null); }}
      title={t(confirmation === "delete" ? "Excluir conta" : "Sair da conta")}
      description={t(confirmation === "delete"
        ? "Excluir a conta remove o dicionário, os snippets e o histórico compartilhados e o acesso ao serviço. Esta ação não pode ser desfeita. Os registros locais serão mantidos."
        : "Ao sair, o Clarify volta ao dicionário e ao processamento locais. As palavras da conta ficam separadas por conta neste computador.")}>
      <Button autoFocus disabled={account.busy || busy} onClick={() => setConfirmation(null)}>{t("Cancelar")}</Button>
      <Button className={confirmation === "delete" ? "destructive" : ""} disabled={account.busy || busy}
        onClick={() => void confirm()}>{t(confirmation === "delete" ? "Confirmar exclusão da conta" : "Sair da conta")}</Button>
    </Confirm>
  </>;
}
