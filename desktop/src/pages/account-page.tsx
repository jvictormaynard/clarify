import { t, uiLanguage } from "../i18n";
import { useRef, useState } from "react";
import { ChevronRight, Gauge, LogIn, RefreshCw, TriangleAlert, UserRound } from "lucide-react";
import { Button, Confirm, Field, Section } from "../components/ui";
import { formatUsageReset, usageProgress } from "../../../shared/usage";
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
  const usage = usageProgress(account.usage);
  const percent = new Intl.NumberFormat(uiLanguage, { style: "percent", maximumFractionDigits: 1 });
  const usageLabel = usage ? t("{v0} usados · {v1} restantes", {
    v0: percent.format(usage.used_percent / 100), v1: percent.format(usage.remaining_percent / 100),
  }) : "";
  const usageNotice = !usage ? "A cota semanal não está disponível. Atualize para tentar novamente."
    : usage.allocation_status === "waiting" ? "Sua conta aguarda a próxima distribuição de cotas."
    : usage.allocation_status === "unfunded" ? "Não há saldo de patrocínio para uma cota neste momento."
    : usage.allocation_status === "inactive" ? "O processamento da conta está inativo."
    : usage.used_percent === 100 && usage.remaining_percent === 0 && usage.reserved_percent === 0
      ? "Você usou toda a sua cota semanal."
    : !usage.hosted_available ? "O processamento da conta está indisponível no momento." : "";
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
        <AccountSignIn account={account} command={command} busy={accountBusy} />
        {account.managed && !account.pending && <Button variant="text" onClick={() => command("logout")}>{t("Continuar sem conta")}</Button>}
        <details className="account-server"><summary>{t("Servidor próprio")}</summary>
          <div className="account-server-fields">
            <Field title={t("Endereço do servidor")} value={server} placeholder="https://…" onChange={e => setServer(e.target.value)} />
            <Button onClick={() => command("configure", server)}>{t("Salvar servidor")}</Button>
          </div>
        </details>
      </Section> : <>
        <Section className="account-card" title={<><UserRound size={16} aria-hidden="true" /><span className="account-email">{account.email}</span></>}>
          <p className="hint">{t("O Clarify gerencia os modelos e provedores da sua conta. Áudio, texto e palavras ativas do dicionário são processados pelo Clarify.")}</p>
          {usage?.allocation_status === "available" && <div className="account-usage">
            <p className="usage-label"><Gauge size={15} aria-hidden="true" />{usageLabel}</p>
            <div className="usage-progress" role="progressbar" aria-label={t("Uso nesta semana")}
              aria-valuemin={0} aria-valuemax={100} aria-valuenow={usage.used_percent} aria-valuetext={usageLabel}>
              <div style={{ width: `${usage.used_percent}%` }} />
            </div>
          </div>}
          {usageNotice && <p role="status" className="hint">{t(usageNotice)}</p>}
          {!usage && <Button onClick={() => command("refresh")}>{t("Retry")}</Button>}
          {usage && <p className="hint">{t("Próxima renovação: {v0}.", { v0: formatUsageReset(usage.reset_at, uiLanguage) })}</p>}
          <p className="hint">{t("Sua cota semanal é individual e vale em todos os seus dispositivos. Ela fica fixa até a renovação.")}</p>
          <p className="hint">{t("Os patrocínios financiam as cotas semanais. A disponibilidade depende do saldo de patrocínio.")}</p>
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
        <details className="danger-zone">
          <summary><TriangleAlert size={15} aria-hidden="true" /><span>{t("Zona de perigo")}</span><ChevronRight size={15} className="account-disclosure" aria-hidden="true" /></summary>
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
