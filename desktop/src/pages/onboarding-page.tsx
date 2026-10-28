import { t } from "../i18n";
import { useState } from "react";
import { ArrowLeft, HardDrive, KeyRound, UserRound } from "lucide-react";
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
    if (account?.signedIn) await run("accountCommand", "logout", "");
    setStep("local");
  };
  const complete = async (mode: "account" | "byok" | "local") => {
    const result = await run("completeOnboarding", mode, key);
    setKey("");
    if (result && !result.onboardingRequired && mode === "local") await navigate("models");
  };
  return <main className="onboarding onboarding-page">
    <div className="onboarding-content">
      <div className="onboarding-heading">
        <ClarifyLogo />
        <h1>{step === "byok" ? t("Use sua chave Groq") : step === "local" ? t("Use um modelo local") : account?.signedIn ? t("Sua conta está pronta") : t("Boas-vindas ao Clarify")}</h1>
        <p className="hint">{t("Fale. O Clarify transforma sua voz em texto claro.")}</p>
      </div>
      {error && <p className="error" role="alert">{t(error)}</p>}
      {account?.error && <p className="error" role="alert">{t(account.error)}</p>}
      <fieldset className={`onboarding-panel${step === "account" && !account?.signedIn ? " onboarding-auth" : ""}`} disabled={busy || account?.busy}>
        {step === "byok" ? <>
          <Field title={t("Chave de API do Groq")} value={key} type="password" autoComplete="off" placeholder="gsk_…" onChange={e => setKey(e.target.value)} />
          <div className="onboarding-note"><KeyRound size={16} aria-hidden="true" /><p className="hint">{t("A chave fica no armazenamento seguro deste computador. Áudio, texto e palavras ativas do dicionário são enviados ao serviço escolhido por você. Ao continuar, você autoriza esse processamento.")}</p></div>
          <Button variant="primary" disabled={!key.trim()} onClick={() => void complete("byok")}>{t("Salvar chave e continuar")}</Button>
        </> : step === "local" ? <>
          <div className="onboarding-note"><HardDrive size={18} aria-hidden="true" /><p>{t("Transcreva neste computador, sem conta nem chave de API. A próxima tela permite baixar e configurar o modelo.")}</p></div>
          <p className="hint">{t("O processamento local não envia áudio para serviços externos. A reescrita por nuvem permanece desativada.")}</p>
          <Button variant="primary" onClick={() => void complete("local")}>{t("Continuar e configurar modelo")}</Button>
          <Button variant="text" onClick={() => setStep("byok")}>{t("Usar minha chave de API")}</Button>
        </> : account && (account.signedIn ? <>
          <p className="onboarding-identity"><UserRound size={16} aria-hidden="true" />{account.email}</p>
          <p className="hint">{t("Para transcrever e reescrever, o Clarify processa áudio, texto e palavras ativas do dicionário. O histórico da conta é sincronizado entre seus dispositivos. Patrocínios financiam uma cota semanal individual. Novas contas podem receber uma cota inicial proporcional ao tempo até a renovação. Sem saldo de patrocínio, a conta aguarda a próxima distribuição.")}</p>
          <Button variant="primary" onClick={() => void complete("account")}>{t("Começar")}</Button>
        </> : <>
          <AccountSignIn account={account} command={command} busy={busy || account.busy}
            guestVariant="primary"
            onContinueWithoutAccount={() => void chooseLocal()} />
        </>)}
        {step !== "account" && <Button variant="text" onClick={() => { setStep(step === "byok" ? "local" : "account"); setKey(""); }}><ArrowLeft size={15} />{t("Voltar")}</Button>}
      </fieldset>
      {account?.socialPending && <Button variant="text" onClick={() => command("cancel-social")}>{t("Cancelar login")}</Button>}
    </div>
  </main>;
}
