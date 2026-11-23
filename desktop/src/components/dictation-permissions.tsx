import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowUpRight, Check, GripVertical, Keyboard, Mic, Type, X } from "lucide-react";
import logo from "../../assets/clarify.png";
import { t, uiLanguage } from "../i18n";
import { electron } from "../platform";
import type { SettingsPageProps } from "../settings/use-settings";
import { Button } from "./ui";

type Permission = "accessibility" | "microphone" | "shortcuts";

const permissions = [
  { id: "accessibility", icon: Type, title: "Colar o ditado em outros apps", description: "Insere o texto onde você está escrevendo." },
  { id: "microphone", icon: Mic, title: "Captar sua voz", description: "Usa o microfone quando você começa a ditar." },
  { id: "shortcuts", icon: Keyboard, title: "Ditar com atalhos em outros apps", description: "Reconhece seu atalho mesmo quando outro app está aberto." },
] as const;

function DragClarify({ tile = false }: { tile?: boolean }) {
  return <div
    className={tile ? "permission-guide-drag" : "permission-drag-inline"}
    draggable
    onDragStart={event => {
      event.preventDefault();
      electron()?.dragInstalledApp?.();
    }}
  >
    <img className="permission-drag-icon" src={logo} alt={t("Ícone do Clarify para arrastar")} draggable={false} />
    {tile && <><span>Clarify</span><GripVertical size={18} aria-hidden="true" /></>}
  </div>;
}

export function PermissionGuide() {
  return <main className="permission-guide">
    <div className="permission-guide-close">
      <Button variant="ghost" size="history-icon" aria-label={t("Fechar")}
        onClick={() => void electron()?.window("dismissPermissionGuide").catch(() => {})}>
        <X size={16} aria-hidden="true" />
      </Button>
    </div>
    <h1>{t("Ative o Clarify nos Ajustes")}</h1>
    <p className="hint">{t("Se o Clarify não aparecer na lista, arraste o item abaixo para lá.")}</p>
    <DragClarify tile />
  </main>;
}

export function DictationPermissions({ controller, progress, onContinue, onSkip }: SettingsPageProps & {
  progress: ReactNode;
  onContinue: () => void;
  onSkip: () => void;
}) {
  const { state, run, busy, error } = controller;
  const heading = useRef<HTMLHeadingElement>(null);
  const nextAction = useRef<HTMLButtonElement>(null);
  const lastRequested = useRef<Permission | undefined>(undefined);
  const mounted = useRef(false);
  const [dragAvailable, setDragAvailable] = useState(false);
  const [showSettingsHelp, setShowSettingsHelp] = useState<Permission>();
  const [waitingForAccess, setWaitingForAccess] = useState(false);
  const status = {
    accessibility: state.dictationPermissions?.accessibility,
    microphone: state.dictationPermissions?.microphone,
    shortcuts: state.inputMonitoringStatus,
  };
  const liveStatus = useRef(status);
  liveStatus.current = status;
  const ready = status.microphone === "allowed";
  const recordingShortcut = state.hotkeyActions.find(action => action.id === "recording_hotkey");
  const shortcutUnavailable = recordingShortcut && state.hotkeyUnavailable?.includes(recordingShortcut.display);
  const next = ready ? undefined : permissions.find(({ id }) => status[id] && status[id] !== "allowed")?.id;
  const requestedStatus = lastRequested.current && status[lastRequested.current];

  useEffect(() => {
    mounted.current = true;
    heading.current?.focus();
    const desktop = electron();
    if (desktop?.dragInstalledApp) void desktop.window("canDragInstalledApp").then(available => {
      if (mounted.current) setDragAvailable(available === true);
    }).catch(() => {});
    return () => {
      mounted.current = false;
      if (desktop?.dragInstalledApp) void desktop.window("dismissPermissionGuide").catch(() => {});
    };
  }, []);

  useEffect(() => {
    if (requestedStatus !== "allowed") return;
    lastRequested.current = undefined;
    void electron()?.window("dismissPermissionGuide").catch(() => {});
    nextAction.current?.focus({ preventScroll: true });
  }, [requestedStatus]);

  async function allow(id: Permission) {
    setWaitingForAccess(false);
    if (showSettingsHelp && showSettingsHelp !== id) {
      setShowSettingsHelp(undefined);
      void electron()?.window("dismissPermissionGuide").catch(() => {});
    }
    lastRequested.current = id;
    const opensSettings = id === "accessibility" || status[id] === "settings";
    const result = id === "shortcuts"
      ? await run("inputMonitoringCommand", opensSettings ? "open" : "request")
      : await run("dictationPermissionCommand", id);
    if (!result || !mounted.current || liveStatus.current[id] === "allowed") return;
    const updatedStatus = id === "shortcuts" ? result.inputMonitoringStatus : result.dictationPermissions?.[id];
    if (updatedStatus === "allowed") return;
    setShowSettingsHelp(opensSettings ? id : undefined);
    if (opensSettings && dragAvailable && id !== "microphone") {
      void electron()?.window("showPermissionGuide", { permission: id, locale: uiLanguage }).catch(() => {});
    }
  }

  return <main className="onboarding onboarding-page onboarding-flow onboarding-practice" data-phase="permissions">
    <div className="onboarding-content">
      {progress}
      <div className="onboarding-heading">
        <img className="permission-brand" src={logo} alt="Clarify" />
        <h1 ref={heading} tabIndex={-1}>{t("Permissões para ditar")}</h1>
        <p className="hint">{t("Permita o microfone para testar o ditado. Os outros acessos são opcionais.")}</p>
      </div>
      <div className="permission-list">
        {permissions.map(({ id, icon: Icon, title, description }) => {
          const allowed = status[id] === "allowed";
          const pending = status[id] === "pending";
          const opensSettings = id === "accessibility" || status[id] === "settings";
          const help = showSettingsHelp === id && !allowed && !pending;
          return <section className="permission-card" data-allowed={allowed} data-next={next === id} key={id}>
            <div className="permission-icon">
              {allowed ? <Check size={18} aria-hidden="true" /> : <Icon size={18} aria-hidden="true" />}
            </div>
            <div className="permission-copy">
              <h2>{t(title)}</h2>
              <p className="hint">{t(id === "shortcuts" && allowed && status.accessibility === "allowed"
                ? "Acessibilidade também permite usar atalhos." : description)}</p>
            </div>
            <div className="permission-action">
              {allowed
                ? <span className="permission-allowed" role="status">{t("Acesso permitido")}</span>
                : <Button
                    ref={next === id ? nextAction : undefined}
                    variant={next === id ? "primary" : "default"}
                    loading={pending}
                    disabled={busy || !status[id] || pending}
                    aria-label={t(help ? "Reabrir Ajustes" : id === "accessibility" ? "Abrir Ajustes de Acessibilidade" : id === "microphone"
                      ? (opensSettings ? "Abrir Ajustes de Microfone" : "Permitir microfone")
                      : (opensSettings ? "Abrir Ajustes do Monitoramento de Entrada" : "Permitir atalhos globais"))}
                    onClick={() => void allow(id)}
                  >
                    {t(help ? "Reabrir Ajustes" : opensSettings ? "Abrir Ajustes" : "Permitir")}
                    {opensSettings && <ArrowUpRight size={14} aria-hidden="true" />}
                  </Button>}
            </div>
            {help && <div className="permission-help">
              {dragAvailable && id !== "microphone" && <DragClarify />}
              <div>
                <p>{t("Ative o Clarify na lista dos Ajustes do Sistema.")}</p>
                {dragAvailable && id !== "microphone" && <p className="hint permission-drag-hint">
                  <GripVertical size={14} aria-hidden="true" />
                  {t("Se o Clarify não estiver na lista, arraste o ícone para lá. Você também pode usar o botão +.")}
                </p>}
                {!dragAvailable && id !== "microphone" && <p className="hint">{t("Se o Clarify não estiver na lista, use o botão + para adicionar o app.")}</p>}
                {id !== "microphone" && <p className="hint">{t("Se o macOS pedir para encerrar e reabrir, a configuração será retomada.")}</p>}
                <div className="permission-recheck">
                  <Button variant="text" disabled={busy} onClick={async () => {
                    if (await run("dictationPermissionCommand", "check")) setWaitingForAccess(true);
                  }}>{t("Verificar acesso")}</Button>
                  {waitingForAccess && <p className="hint" role="status">{t("O macOS ainda não confirmou o acesso. Se o Clarify já estiver ativado nos Ajustes, encerre e reabra o app.")}</p>}
                </div>
              </div>
            </div>}
          </section>;
        })}
      </div>
      {status.shortcuts === "allowed" && shortcutUnavailable && <div className="onboarding-feedback" role="status">
        <p className="hint">{t("O macOS liberou o acesso ao teclado, mas o atalho ainda está indisponível.")}</p>
        <Button variant="text" disabled={busy} onClick={() => void run("dictationPermissionCommand", "check")}>{t("Verificar acesso")}</Button>
      </div>}
      {error && <p className="onboarding-feedback" role="alert">{t(error)}</p>}
      <div className="onboarding-flow-actions onboarding-practice-actions onboarding-practice-footer">
        <Button ref={!next ? nextAction : undefined} variant="primary" disabled={busy || !ready} onClick={async () => {
          const confirmed = await run("dictationPermissionCommand", "check");
          if (confirmed && confirmed.dictationPermissions?.microphone === "allowed") onContinue();
        }}>{t("Continuar")}</Button>
        <Button variant="text" disabled={busy} onClick={onSkip}>{t("practice_skip")}</Button>
      </div>
    </div>
  </main>;
}
