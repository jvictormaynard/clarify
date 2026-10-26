import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import type { ChatGPTAction } from "../settings/bridge";
import { Button, Confirm, Picker, Row } from "./ui";

export function ChatGPTPlan({ controller }: SettingsPageProps) {
  const { state, run, validateProvider, validatingProvider } = controller;
  const account = state.chatgptState;
  const connected = account?.connected === true;
  const enabled = connected && account?.planEnabled === true;
  const busy = account?.busy === true;
  const command = (action: ChatGPTAction, value = "") =>
    run("chatgptCommand", action, value);
  const options = (account?.accounts ?? []).map(item => ({ ...item,
    label: account!.accounts.some(other => other.id !== item.id && other.label === item.label)
      ? `${item.label} · ${item.id}` : item.label,
  }));
  return (
    <>
      <p className="hint">{t("Use seu plano ChatGPT Plus ou Pro para tarefas de texto. O texto é enviado à OpenAI. O uso compartilha os limites do seu plano, sem cota adicional. A transcrição de áudio não está incluída.")}</p>
      <p className="hint" role="status">
        {enabled ? t("Plano ChatGPT conectado") : connected
          ? t("Conta conectada. O uso do plano ChatGPT não foi autorizado.")
          : t("ChatGPT não conectado")}
      </p>
      {options.length > 0 && (
        <Row title={t("Conta ChatGPT")}>
          <Picker label={t("Conta ChatGPT")} value={account?.accountId ?? ""}
            options={options} disabled={busy || state.providerBusy || state.routeModelStatus === "loading"}
            onChange={value => void command("select_account", value)} />
        </Row>
      )}
      {account?.error && <p className="hint" role="alert">{t(account.error)}</p>}
      {state.providerError && state.providerError !== account?.error &&
        <p className="hint" role="alert">{t(state.providerError)}</p>}
      <div className="inline-actions">
        {busy ? (
          <Button onClick={() => void command("cancel")}>{t("Cancelar")}</Button>
        ) : (
          <>
            {!enabled && <Button onClick={() => void command("sign_in")}>{t("Continuar com ChatGPT")}</Button>}
            {connected && <>
              <Button disabled={state.providerBusy || state.routeModelStatus === "loading"}
                onClick={() => void command("add_account")}>{t("Adicionar conta ChatGPT")}</Button>
              <Button variant="text" disabled={state.providerBusy || state.routeModelStatus === "loading"}
                onClick={() => void command("sign_out")}>{t("Sair do ChatGPT")}</Button>
            </>}
            {enabled && <Button disabled={state.providerBusy || validatingProvider}
              onClick={() => void validateProvider()}>{state.providerBusy ? t("Carregando…") : t("Atualizar modelos ChatGPT")}</Button>}
          </>
        )}
        <Button variant="text" disabled={busy}
          onClick={() => void command("manage_usage")}>{t("Gerenciar uso no ChatGPT")}</Button>
      </div>
      <Confirm open={enabled && account?.planNoticeSeen === false}
        title={t("Você está usando seu plano ChatGPT")}
        description={t("As tarefas de texto que você configurar com ChatGPT usarão seu plano. Gerencie os limites nas configurações do ChatGPT. A conexão não altera os serviços dos seus fluxos.")}
        onOpenChange={open => { if (!open && !busy) void command("dismiss_notice"); }}>
        <Button disabled={busy} onClick={() => void command("dismiss_notice")}>{t("Entendi")}</Button>
      </Confirm>
    </>
  );
}
