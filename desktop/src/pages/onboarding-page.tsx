import { useState } from "react";
import { ArrowLeft } from "lucide-react";
import { AccountSignIn } from "../components/account-sign-in";
import { ClarifyLogo } from "../components/clarify-logo";
import { Button, Field } from "../components/ui";
import type { SettingsPageProps } from "../settings/use-settings";

export function OnboardingPage({ controller }: SettingsPageProps) {
  const { state, busy, error, run, navigate } = controller;
  const account = state.accountState;
  const [step, setStep] = useState<"account" | "byok" | "local">("account");
  const [key, setKey] = useState("");
  const command = (action: string, value = "") => void run("accountCommand", action, value);
  const chooseLocal = async () => {
    if (account?.pending) await run("accountCommand", "logout", "");
    if (account?.hosted) await run("accountCommand", "hosted", "0");
    setStep("local");
  };
  const complete = async (mode: "account" | "byok" | "local") => {
    const result = await run("completeOnboarding", mode, key);
    setKey("");
    if (result && !result.onboardingRequired && mode === "local") await navigate("models");
  };
  return <main className="onboarding">
    <div className="onboarding-content">
      <ClarifyLogo />
      <h1>{step === "byok" ? "Use sua chave Groq" : step === "local" ? "Use um modelo local" : account?.signedIn ? "Sua conta está pronta" : "Boas-vindas ao Clarify"}</h1>
      <p className="hint">Fale. O Clarify transforma sua voz em texto claro.</p>
      {error && <p className="error" role="alert">{error}</p>}
      {account?.error && <p className="error" role="alert">{account.error}</p>}
      <fieldset disabled={busy}>
        {step === "byok" ? <>
          <Field title="Chave de API do Groq" value={key} type="password" autoComplete="off" placeholder="gsk_…" onChange={e => setKey(e.target.value)} />
          <p className="hint">A chave fica no armazenamento seguro deste computador. Áudio, texto e palavras ativas do dicionário são enviados diretamente ao Groq. Ao continuar, você autoriza esse processamento.</p>
          <Button variant="primary" disabled={!key.trim()} onClick={() => void complete("byok")}>Salvar chave e continuar</Button>
        </> : step === "local" ? <>
          <p>Transcreva neste computador, sem conta nem chave de API. A próxima tela permite baixar e configurar o modelo.</p>
          <p className="hint">O processamento local não envia áudio ao Clarify ou ao Groq. A reescrita por nuvem permanece desativada.</p>
          <Button variant="primary" onClick={() => void complete("local")}>Continuar e configurar modelo</Button>
          <Button variant="text" onClick={() => setStep("byok")}>Usar minha chave de API</Button>
        </> : account && (account.signedIn ? <>
          <p>{account.email}</p>
          <p className="hint">Para transcrever e reescrever, áudio, texto e palavras ativas do dicionário serão enviados ao Clarify e ao Groq. O histórico fica neste computador. A conta inclui até 300 minutos por mês, sujeitos à disponibilidade do beta.</p>
          {!account.hosted ? <Button variant="primary" onClick={() => command("hosted", "1")}>Ativar processamento do Clarify</Button> : <Button variant="primary" onClick={() => void complete("account")}>Começar</Button>}
        </> : <>
          <AccountSignIn account={account} command={command} />
          <Button variant="text" className="onboarding-skip" onClick={() => void chooseLocal()}>continuar 100% local</Button>
        </>)}
        {step !== "account" && <Button variant="text" onClick={() => { setStep(step === "byok" ? "local" : "account"); setKey(""); }}><ArrowLeft size={15} /> Voltar</Button>}
        {busy && <p className="hint" role="status">Aguarde…</p>}
      </fieldset>
    </div>
  </main>;
}
