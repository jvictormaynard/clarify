import { t } from "../i18n";
import { useLayoutEffect, useRef, useState } from "react";
import { ArrowLeft, HardDrive, Mail } from "lucide-react";
import { Button, Field } from "./ui";
import { ProviderBrandIcon } from "./provider-brand-icon";
import type { Settings } from "../settings/bridge";

export function AccountSignIn({ account, command, busy = false, onContinueWithoutAccount, guestVariant = "default" }: {
  account: NonNullable<Settings["accountState"]>;
  command: (action: string, value?: string) => void;
  busy?: boolean;
  onContinueWithoutAccount?: () => void;
  guestVariant?: "default" | "primary";
}) {
  const [email, setEmail] = useState(account.email || "");
  const [code, setCode] = useState("");
  const [emailEntry, setEmailEntry] = useState(!!account.pending);
  const emailInput = useRef<HTMLInputElement>(null);
  const emailChoice = useRef<HTMLButtonElement>(null);
  const returnToChoice = useRef(false);
  useLayoutEffect(() => {
    if (account.socialPending || account.pending) return;
    if (emailEntry) emailInput.current?.focus();
    else if (returnToChoice.current) {
      returnToChoice.current = false;
      emailChoice.current?.focus();
    }
  }, [emailEntry, account.pending, account.socialPending]);
  if (account.socialPending) return <p role="status" className="hint">{t("Conclua o login no navegador e volte ao Clarify.")}</p>;
  return <form className="account-sign-in" onSubmit={event => {
    event.preventDefault();
    if (!account.pending && !emailEntry) return;
    if (account.pending ? code.trim() : email.trim() && account.endpoint) {
      command(account.pending ? "confirm" : "login", account.pending ? code : email);
      setCode("");
    }
  }}>{account.pending ? <>
    <p className="hint">{t("Digite o código enviado para {v0}. O código vale por 10 minutos.", { v0: account.email })}</p>
    <Field className="min-h-10.5" title={t("Código recebido por e-mail")} value={code} inputMode="numeric" autoComplete="one-time-code" maxLength={16} required onChange={e => setCode(e.target.value)} />
    <Button variant="primary" type="submit" loading={busy} disabled={!code.trim()}>{t("Confirmar código")}</Button>
    <Button variant="text" onClick={() => command("logout")}><ArrowLeft size={16} aria-hidden />{t("Voltar")}</Button>
  </> : emailEntry ? <>
    <Field ref={emailInput} className="min-h-10.5" title={t("E-mail")} type="email" value={email} autoComplete="email" required maxLength={254} placeholder="email@example.com" onChange={e => setEmail(e.target.value)} />
    <p className="hint">{t("Enviaremos um código para entrar ou criar sua conta. Você não precisa de senha.")}</p>
    <Button variant="primary" type="submit" loading={busy} disabled={!email.trim() || !account.endpoint}>{t("Continuar")}</Button>
    <Button variant="text" disabled={busy} onClick={() => { returnToChoice.current = true; setEmailEntry(false); }}><ArrowLeft size={16} aria-hidden />{t("Voltar")}</Button>
  </> : <div className="social-sign-in" aria-label={t("Entrar com outra conta")}>
    {(["Google", "Microsoft", "GitHub"] as const).map(provider => <Button key={provider}
      className={provider === "Google" ? "google-sign-in" : undefined}
      disabled={busy || !account.endpoint} onClick={() => command("social", provider.toLowerCase())}>
      <ProviderBrandIcon provider={provider} className="text-foreground" />
      {t("Continuar com {v0}", { v0: provider })}
    </Button>)}
    <Button ref={emailChoice} disabled={busy || !account.endpoint} onClick={() => setEmailEntry(true)}>
      <Mail className="size-5" aria-hidden />{t("Continuar com e-mail")}
    </Button>
  </div>}
    {!account.pending && onContinueWithoutAccount && <div className="auth-guest-action">
      <p className="auth-guest-separator">{t("Ou continue sem conta")}</p>
      <Button className="auth-guest-button" variant={emailEntry ? "default" : guestVariant} disabled={busy} onClick={onContinueWithoutAccount}>
        <HardDrive className="size-5" aria-hidden />{t("Continuar sem conta")}
      </Button>
    </div>}
  </form>;
}
