import { useEffect, useRef, useState } from "react";
import { Tooltip } from "@base-ui/react/tooltip";
import { ArrowLeft, ArrowRight, Check, Copy, Info, Mic, Sparkles, X } from "lucide-react";
import { t } from "../i18n";
import { Button } from "./ui";
import { Button as IconButton } from "./primitives/button";
import { Dialog, DialogPopup, DialogTitle, DialogDescription } from "./primitives/dialog";
import logo from "../../src-tauri/icons/clarify.png";
import "../styles/feature-guide.css";

export type GuideKind = "snippets" | "dictionary" | "actions";

type GuideStep = { title: string; description: string; note?: string };
const guides: Record<GuideKind, { name: string; steps: GuideStep[] }> = {
  snippets: { name: "Snippets", steps: [
    { title: "Salve uma frase", description: "Adicione a frase e o texto que ela insere. Salve para aplicar." },
    { title: "Diga a frase", description: "Dite apenas a frase de ativação." },
    { title: "Insira o texto salvo", description: "O texto é inserido exatamente como você salvou.", note: "Em mensagens maiores, a reescrita pode ajustar o texto e enviá-lo à IA." },
  ] },
  dictionary: { name: "Dicionário", steps: [
    { title: "Adicione um termo", description: "Escreva o nome como ele deve aparecer." },
    { title: "Ajuste a pronúncia", description: "Pronúncia e variações são opcionais. Salve para aplicar." },
    { title: "Dite normalmente", description: "O termo ajuda a transcrição e a revisão, quando compatíveis.", note: "Não treina o modelo nem garante a grafia. Termos usados na nuvem são enviados ao serviço." },
  ] },
  actions: { name: "Ações", steps: [
    { title: "Crie uma ação", description: "Dê um nome e escreva o que ela deve fazer." },
    { title: "Adicione o texto", description: "Abra a ação e cole o texto que deseja transformar." },
    { title: "Execute e copie", description: "Execute a ação. Revise o resultado e copie quando quiser." },
  ] },
};

function GuideScene({ kind, step }: { kind: GuideKind; step: number }) {
  const signature = t("Atenciosamente,\nAlex");
  const source = kind === "snippets" ? t("minha assinatura") : kind === "dictionary" ? "clarifai" : t("oi, pode enviar o arquivo hoje?");
  const result = kind === "snippets" ? signature : kind === "dictionary" ? "Clarify" : t("Olá! Você pode enviar o arquivo hoje?");
  return <div className="guide-scene" aria-hidden="true">
    {step === 0 ? <div className="guide-example guide-example-editor">
      <div className="guide-example-brand"><img src={logo} alt="" /><span>{t(guides[kind].name)}</span></div>
      <div className="guide-example-field"><span>{t(kind === "snippets" ? "Frase de ativação" : kind === "dictionary" ? "Termo" : "Nome da ação")}</span><div className="guide-reveal">{kind === "snippets" ? source : kind === "dictionary" ? "Clarify" : t("Mais claro")}</div></div>
      {kind !== "dictionary" && <div className="guide-example-field"><span>{t(kind === "snippets" ? "Texto a inserir" : "Instruções da ação")}</span><div className="guide-reveal guide-reveal-later">{kind === "snippets" ? signature : t("Reescreva com clareza.")}</div></div>}
      <span className="guide-save">{t("Salvar")}<Check size={14} /></span>
    </div> : kind === "dictionary" && step === 1 ? <div className="guide-example guide-example-editor">
      <div className="guide-example-field"><span>{t("Termo")}</span><div>Clarify</div></div>
      <div className="guide-example-field"><span>{t("Pronúncia (opcional)")}</span><div className="guide-reveal">clarifai</div></div>
      <span className="guide-save">{t("Salvar")}<Check size={14} /></span>
    </div> : <>
      <div className={"guide-example guide-example-message " + (step === 2 ? "guide-result" : "guide-source")}>
        <span className="guide-example-label">{t(step === 2 ? "Resultado" : kind === "actions" ? "Texto" : "Ditado")}</span>
        <div className="guide-message-text"><span className="guide-reveal">{step === 2 ? result : source}</span></div>
        {step === 2 && <span className="guide-result-mark">{kind === "actions" ? <><Copy className="guide-copy-icon" size={18} /><Check className="guide-check-icon" size={18} /></> : <Check size={18} />}</span>}
      </div>
      <div className="guide-pill"><img src={logo} alt="" />{kind === "actions" ? <><Sparkles size={18} /><span>{t("Executar ação")}</span></> : <><Mic size={18} /><div className="guide-wave">{[14, 22, 30, 18, 26, 16, 24].map((height, index) => <i key={index} style={{ height, animationDelay: index * -0.11 + "s" }} />)}</div></>}</div>
    </>}
  </div>;
}

export function FeatureGuide({ kind }: { kind: GuideKind }) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);
  const [direction, setDirection] = useState(1);
  const trigger = useRef<HTMLButtonElement>(null);
  const guide = guides[kind];
  const current = guide.steps[step];
  const move = (delta: number) => {
    setDirection(delta);
    setStep(previous => Math.max(0, Math.min(guide.steps.length - 1, previous + delta)));
  };
  return <>
    <Tooltip.Provider delay={180}><Tooltip.Root>
      <Tooltip.Trigger id={"feature-guide-trigger-" + kind} render={<Button ref={trigger} className="guide-info-button" variant="ghost" aria-label={t("Como funciona")} aria-haspopup="dialog" aria-expanded={open} onClick={() => { setStep(0); setDirection(1); setOpen(true); }} />}><Info size={18} aria-hidden /></Tooltip.Trigger>
      <Tooltip.Portal><Tooltip.Positioner side="top" sideOffset={8} className="guide-tooltip-positioner"><Tooltip.Popup role="tooltip" className="guide-tooltip">{t("Como funciona")}</Tooltip.Popup></Tooltip.Positioner></Tooltip.Portal>
    </Tooltip.Root></Tooltip.Provider>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogPopup className="feature-guide-dialog" bottomStickOnMobile={false} finalFocus={trigger} onKeyDown={event => {
        if (event.key === "ArrowRight" || event.key === "ArrowLeft") { event.preventDefault(); move(event.key === "ArrowRight" ? 1 : -1); }
      }}>
        <DialogTitle className="sr-only">{t("Como funciona: {name}", { name: t(guide.name) })}</DialogTitle>
        <div className="feature-guide-stage" data-guide={kind}>
          <div className="guide-backdrop" aria-hidden="true"><i /><i /><i /></div>
          <div key={step} data-direction={direction > 0 ? "next" : "previous"} className="guide-step-visual"><GuideScene kind={kind} step={step} /></div>
          <Button variant="ghost" className="guide-step-arrow guide-step-previous" disabled={step === 0} aria-label={t("Etapa anterior")} onClick={() => move(-1)}><ArrowLeft size={20} aria-hidden /></Button>
          <Button variant="ghost" className="guide-step-arrow guide-step-next" disabled={step === guide.steps.length - 1} aria-label={t("Próxima etapa")} onClick={() => move(1)}><ArrowRight size={20} aria-hidden /></Button>
        </div>
        <div className="feature-guide-copy" key={kind + step}>
          <div role="status" aria-live="polite" aria-atomic="true">
            <span className="guide-step-count">{t("Etapa {current} de {total}", { current: step + 1, total: guide.steps.length })}</span>
            <h3>{t(current.title)}</h3>
            <DialogDescription>{t(current.description)}</DialogDescription>
          </div>
          {current.note && <p className="guide-note">{t(current.note)}</p>}
          <div className="guide-progress"><ol aria-label={t("Etapas")}>{guide.steps.map((_, index) => <li key={index} aria-current={step === index ? "step" : undefined}><span className="sr-only">{index + 1}</span></li>)}</ol>
            {step === guide.steps.length - 1 && <Button variant="primary" onClick={() => setOpen(false)}>{t("Concluído")}</Button>}
          </div>
        </div>
      </DialogPopup>
    </Dialog>
  </>;
}


/** Dismissible first-use cards share the modal's scenes. */
export function FeatureGuideCard({ kind }: { kind: GuideKind }) {
  const key = "clarify.feature-guide-card.dismissed.v1." + kind;
  const [dismissed, setDismissed] = useState(() => {
    try { return localStorage.getItem(key) === "true"; } catch { return false; }
  });
  const [step, setStep] = useState(0);
  const [focused, setFocused] = useState(false);
  const [reduced, setReduced] = useState(() => matchMedia("(prefers-reduced-motion: reduce)").matches);
  const [visible, setVisible] = useState(() => !document.hidden);
  useEffect(() => {
    const motion = matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(motion.matches);
    const visibility = () => setVisible(!document.hidden);
    motion.addEventListener("change", update);
    document.addEventListener("visibilitychange", visibility);
    return () => { motion.removeEventListener("change", update); document.removeEventListener("visibilitychange", visibility); };
  }, []);
  useEffect(() => {
    if (dismissed || reduced || focused || !visible) return;
    const timer = window.setTimeout(() => {
      if (document.hidden || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
      setStep(current => (current + 1) % guides[kind].steps.length);
    }, 6000);
    return () => window.clearTimeout(timer);
  }, [dismissed, reduced, focused, visible, kind, step]);
  if (dismissed) return null;
  const guide = guides[kind], current = guide.steps[step];
  const dismiss = () => {
    try { localStorage.setItem(key, "true"); } catch { /* Still hide for this visit. */ }
    setDismissed(true);
    document.getElementById("feature-guide-trigger-" + kind)?.focus();
  };
  return <aside className="feature-guide-card" data-guide={kind} aria-label={t("Como funciona: {name}", { name: t(guide.name) })}
    onFocusCapture={() => setFocused(true)} onBlurCapture={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setFocused(false); }}>
    <div className="guide-backdrop" aria-hidden="true"><i /><i /><i /></div>
    <div className="guide-card-copy">
      <div key={step} className="guide-card-text"><h3>{t(current.title)}</h3><p>{t(current.description)}</p></div>
      <div className="guide-card-progress" aria-label={t("Etapas")}>{guide.steps.map((_, index) => <button type="button" key={index}
        aria-label={t("Etapa {current} de {total}", { current: index + 1, total: guide.steps.length })} aria-pressed={step === index} onClick={() => setStep(index)}><span /></button>)}</div>
    </div>
    <div className="guide-card-visual" aria-hidden="true"><div className="guide-card-frame"><div key={step} className="guide-card-scene"><GuideScene kind={kind} step={step} /></div></div></div>
    <IconButton size="icon" variant="ghost" className="absolute end-2 top-2" aria-label={t("Fechar guia de {name}", { name: t(guide.name) })} onClick={dismiss}><X aria-hidden /></IconButton>
  </aside>;
}
