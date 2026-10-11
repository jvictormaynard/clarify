import { useState } from "react";
import { AudioLines, ArrowLeft } from "lucide-react";
import { AccountSignIn } from "../components/account-sign-in";
import { Button, Field } from "../components/ui";
import type { SettingsPageProps } from "../settings/use-settings";

export function OnboardingPage({ controller }: SettingsPageProps) {
  const { state, busy, error, run, navigate } = controller;
  const account = state.accountState;
  const [step, setStep] = useState<"welcome" | "login" | "signup" | "byok" | "local">(() => account?.signedIn || account?.pending ? "login" : "welcome");
  const [key, setKey] = useState("");
  const command = (action: string, value = "") => void run("accountCommand", action, value);
  const choosePersonal = (mode: "byok" | "local") => {
    if (account?.hosted) command("hosted", "0");
    setStep(mode);
  };
  const complete = async (mode: "account" | "byok" | "local") => {
    const result = await run("completeOnboarding", mode, key);
    setKey("");
    if (result && !result.onboardingRequired && mode === "local") await navigate("models");
  };
  return <main className="onboarding">
    <div className="onboarding-content">
      <AudioLines size={42} strokeWidth={2} aria-hidden="true" />
      <h1>{step === "welcome" ? "Boas-vindas ao Clarify" : step === "byok" ? "Use sua chave Groq" : step === "local" ? "Use um modelo local" : account?.signedIn ? "Sua conta está pronta" : step === "signup" ? "Crie sua conta" : "Entre no Clarify"}</h1>
      <p className="hint">Fale. O Clarify transforma sua voz em texto claro.</p>
      {error && <p className="error" role="alert">{error}</p>}
      {account?.error && <p className="error" role="alert">{account.error}</p>}
      <fieldset disabled={busy}>
        {step === "welcome" ? <div className="onboarding-options">
          <p>Use uma conta para ditar sem chave de API e compartilhar seu dicionário entre o computador e o iPhone.</p>
          <Button variant="primary" onClick={() => setStep("login")}>Entrar</Button>
          <Button onClick={() => setStep("signup")}>Criar conta</Button>
          <Button variant="ghost" onClick={() => choosePersonal("byok")}>Usar minha chave de API</Button>
          <Button variant="text" onClick={() => choosePersonal("local")}>Usar modelo local</Button>
        </div> : step === "byok" ? <>
          <Field title="Chave de API do Groq" value={key} type="password" autoComplete="off" placeholder="gsk_…" onChange={e => setKey(e.target.value)} />
          <p className="hint">A chave fica no armazenamento seguro deste computador. Áudio, texto e palavras ativas do dicionário são enviados diretamente ao Groq. Ao continuar, você autoriza esse processamento.</p>
          <Button variant="primary" disabled={!key.trim()} onClick={() => void complete("byok")}>Salvar chave e continuar</Button>
        </> : step === "local" ? <>
          <p>Transcreva neste computador, sem conta nem chave de API. A próxima tela permite baixar e configurar o modelo.</p>
          <p className="hint">O processamento local não envia áudio ao Clarify ou ao Groq. A reescrita por nuvem permanece desativada.</p>
          <Button variant="primary" onClick={() => void complete("local")}>Continuar e configurar modelo</Button>
        </> : account && (account.signedIn ? <>
          <p>{account.email}</p>
          <p className="hint">Para transcrever e reescrever, áudio, texto e palavras ativas do dicionário serão enviados ao Clarify e ao Groq. O histórico fica neste computador. A conta inclui até 300 minutos por mês, sujeitos à disponibilidade do beta.</p>
          {!account.hosted ? <Button variant="primary" onClick={() => command("hosted", "1")}>Ativar processamento do Clarify</Button> : <Button variant="primary" onClick={() => void complete("account")}>Começar</Button>}
        </> : <AccountSignIn account={account} command={command} intent={step} />)}
        {step !== "welcome" && <Button variant="text" onClick={() => { setStep("welcome"); setKey(""); }}><ArrowLeft size={15} /> Voltar</Button>}
        {busy && <p className="hint" role="status">Aguarde…</p>}
      </fieldset>
    </div>
  </main>;
}
