import { t } from "../i18n";
import { useState } from "react";
import { Button, Field } from "./ui";
import type { Settings } from "../settings/bridge";

export function AccountSignIn({ account, command, busy = false }: {
  account: NonNullable<Settings["accountState"]>;
  command: (action: string, value?: string) => void;
  busy?: boolean;
}) {
  const [email, setEmail] = useState(account.email || "");
  const [code, setCode] = useState("");
  if (account.socialPending) return <p role="status" className="hint">{t("Conclua o login no navegador e volte ao Clarify.")}</p>;
  return <form className="account-sign-in" onSubmit={event => {
    event.preventDefault();
    if (account.pending ? code.trim() : email.trim() && account.endpoint) {
      command(account.pending ? "confirm" : "login", account.pending ? code : email);
      setCode("");
    }
  }}>{account.pending ? <>
    <p className="hint">{t("Digite o código enviado para {v0}. O código vale por 10 minutos.", { v0: account.email })}</p>
    <Field title={t("Código recebido por e-mail")} value={code} inputMode="numeric" autoComplete="one-time-code" maxLength={16} required onChange={e => setCode(e.target.value)} />
    <Button variant="primary" type="submit" loading={busy} disabled={!code.trim()}>{t("Confirmar código")}</Button>
    <Button variant="text" onClick={() => command("logout")}>{t("Voltar")}</Button>
  </> : <>
    <div className="social-sign-in" aria-label={t("Entrar com outra conta")}>
      {(["Google", "Microsoft", "GitHub"] as const).map(provider => <Button key={provider}
        disabled={busy || !account.endpoint} onClick={() => command("social", provider.toLowerCase())}>
        {t("Continuar com {v0}", { v0: provider })}
      </Button>)}
    </div>
    <p className="hint">{t("Ou continue com seu e-mail")}</p>
    <Field title={t("E-mail")} type="email" value={email} autoComplete="email" required maxLength={254} placeholder="email@example.com" onChange={e => setEmail(e.target.value)} />
    <p className="hint">{t("Enviaremos um código para entrar ou criar sua conta. Você não precisa de senha.")}</p>
    <Button variant="primary" type="submit" loading={busy} disabled={!email.trim() || !account.endpoint}>{t("Continuar")}</Button>
  </>}</form>;
}
