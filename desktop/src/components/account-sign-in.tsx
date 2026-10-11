import { useState } from "react";
import { Button, Field, Row } from "./ui";
import type { Settings } from "../settings/bridge";

export function AccountSignIn({ account, command, intent }: {
  account: NonNullable<Settings["accountState"]>;
  command: (action: string, value?: string) => void;
  intent?: "login" | "signup";
}) {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  return account.pending ? <>
    <p className="hint">Digite o código enviado para {account.email}. O código vale por 10 minutos.</p>
    <Field title="Código recebido por e-mail" value={code} inputMode="numeric" autoComplete="one-time-code" maxLength={16} onChange={e => setCode(e.target.value)} />
    <Button variant="primary" disabled={!code.trim()} onClick={() => { command("confirm", code); setCode(""); }}>Confirmar código</Button>
    <Button onClick={() => command("logout")}>Cancelar entrada</Button>
  </> : <>
    <Field title="E-mail" type="email" value={email} autoComplete="email" onChange={e => setEmail(e.target.value)} />
    <Row title="Receber um código por e-mail" hint="Você não precisa criar uma senha.">
      {intent !== "signup" && <Button variant={intent ? "primary" : "default"} disabled={!email.trim() || !account.endpoint} onClick={() => command("login", email)}>Entrar</Button>}
      {intent !== "login" && <Button variant={intent ? "primary" : "default"} disabled={!email.trim() || !account.endpoint} onClick={() => command("signup", email)}>Criar conta</Button>}
    </Row>
  </>;
}
