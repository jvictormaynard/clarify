import { useState } from "react";
import { Button, Field } from "./ui";
import type { Settings } from "../settings/bridge";

export function AccountSignIn({ account, command }: {
  account: NonNullable<Settings["accountState"]>;
  command: (action: string, value?: string) => void;
}) {
  const [email, setEmail] = useState(account.email || "");
  const [code, setCode] = useState("");
  return <form className="account-sign-in" onSubmit={event => {
    event.preventDefault();
    if (account.pending ? code.trim() : email.trim() && account.endpoint) {
      command(account.pending ? "confirm" : "login", account.pending ? code : email);
      setCode("");
    }
  }}>{account.pending ? <>
    <p className="hint">Digite o código enviado para {account.email}. O código vale por 10 minutos.</p>
    <Field title="Código recebido por e-mail" value={code} inputMode="numeric" autoComplete="one-time-code" maxLength={16} required onChange={e => setCode(e.target.value)} />
    <Button variant="primary" type="submit" disabled={!code.trim()}>Confirmar código</Button>
    <Button variant="text" onClick={() => command("logout")}>Usar outro e-mail</Button>
  </> : <>
    <Field title="E-mail" type="email" value={email} autoComplete="email" required maxLength={254} placeholder="voce@exemplo.com" onChange={e => setEmail(e.target.value)} />
    <p className="hint">Enviaremos um código para entrar ou criar sua conta. Você não precisa de senha.</p>
    <Button variant="primary" type="submit" disabled={!email.trim() || !account.endpoint}>Continuar</Button>
  </>}</form>;
}
