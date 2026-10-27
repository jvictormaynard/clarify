import { useEffect, useRef, useState } from "react";
import { LoaderCircle, Smartphone } from "lucide-react";
import { t } from "../i18n";
import { Button, Row, Section, Switch } from "./ui";
import { call, getComputerPairing } from "../settings/bridge";
import type { SettingsPageProps } from "../settings/use-settings";

const errors: Record<string, string> = {
  unavailable: "O acesso pelo celular não está disponível nesta versão.",
  qr_unavailable: "Não foi possível gerar o QR. Atualize o Clarify e tente novamente.",
  failed: "Não foi possível alterar o acesso do celular. Verifique a conexão e tente novamente.",
};

export function ComputerAccess({ controller }: SettingsPageProps) {
  const { state, run, closing } = controller;
  const access = state.computerState;
  const [open, setOpen] = useState(false);
  const [image, setImage] = useState("");
  const [expires, setExpires] = useState(0);
  const [now, setNow] = useState(Date.now() / 1000);
  const [readError, setReadError] = useState(false);
  const autoPair = useRef(false);
  const qrContainer = useRef<HTMLDivElement>(null);
  const panelGeneration = useRef(0);
  const managed = !!(state.accountState?.signedIn || state.accountState?.managed || state.accountState?.hosted);
  const busy = !!access?.busy;

  const close = () => {
    panelGeneration.current += 1;
    autoPair.current = false;
    setImage(""); setExpires(0); setOpen(false); setReadError(false);
    void call("computerCommand", "close", "").catch(() => {});
  };
  useEffect(() => {
    const hidden = () => { if (document.hidden) close(); };
    document.addEventListener("visibilitychange", hidden);
    return () => {
      panelGeneration.current += 1;
      document.removeEventListener("visibilitychange", hidden);
      void call("computerCommand", "close", "").catch(() => {});
    };
  }, []);
  useEffect(() => { if (closing || managed) close(); }, [closing, managed]);
  useEffect(() => {
    if (!open) return;
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(timer);
  }, [open]);
  useEffect(() => {
    if (open && autoPair.current && access?.running && !busy) {
      autoPair.current = false;
      void run("computerCommand", "pair", "");
    }
  }, [open, access?.running, busy, run]);
  useEffect(() => {
    setImage(""); setExpires(0);
    if (!open || !access?.pairingReady || managed) return;
    let live = true;
    const generation = panelGeneration.current;
    void getComputerPairing().then(pairing => {
      if (live && generation === panelGeneration.current && pairing.expiresAt && pairing.expiresAt > Date.now() / 1000) {
        setImage(pairing.image ?? ""); setExpires(pairing.expiresAt);
      }
    }).catch(() => { if (live) setReadError(true); });
    return () => { live = false; };
  }, [open, access?.pairingReady, access?.pairingExpiresAt, managed]);
  useEffect(() => {
    if (expires && now >= expires) { setImage(""); setExpires(0); }
  }, [now, expires]);
  useEffect(() => {
    if (image) qrContainer.current?.scrollIntoView({ block: "nearest" });
  }, [image]);

  const pair = () => {
    setImage(""); setExpires(0); setReadError(false);
    void run("computerCommand", "pair", "");
  };
  const error = readError ? errors.failed : access?.error ? errors[access.error] ?? errors.failed : "";
  return <Section title={t("Acesso pelo celular")}>
    <Row title={t("Conectar celular")}
      hint={managed ? t("Saia da conta Clarify para conectar o celular aos seus modelos e serviços pessoais.")
        : t("Use seus modelos e serviços deste computador no iPhone. Mantenha o computador ligado e conectado à rede.")}>
      <Button disabled={managed || !access || access.error === "unavailable" || access.blocked || busy}
        onClick={() => { setOpen(true); if (access?.running) pair(); }}>
        <Smartphone size={16} />{t("Conectar celular")}
      </Button>
    </Row>
    {access?.enabled && <>
      <p className="hint" role="status">{access.running ? t("Acesso ativo neste computador.") : t("O computador está offline. Pare o acesso e tente novamente.")}</p>
      {access.running && <p className="hint" role="status">{access.relayConfigured
        ? access.relayConnected ? t("Acesso pela internet ativo.")
          : t("A conexão pela internet está indisponível. O acesso na mesma rede continua ativo.")
        : t("Acesso disponível na mesma rede Wi-Fi.")}</p>}
      <Row title={t("Manter acesso ao iniciar o Clarify")}
        hint={t("Ative apenas se quiser aceitar conexões após reiniciar o aplicativo.")}>
        <Switch label={t("Manter acesso ao iniciar o Clarify")} checked={access.durable} disabled={busy}
          onChange={value => void run("computerCommand", "durable", String(value))} />
      </Row>
      <Section title={t("Celulares pareados")}>
        {access.devices.length === 0 ? <p className="hint">{t("Nenhum celular pareado.")}</p>
          : <ul className="computer-devices">{access.devices.map(device => <li key={device.id}>
            <span>{device.name || t("Celular")}</span>
            <Button disabled={busy} aria-label={t("Revogar acesso de {name}", { name: device.name || t("Celular") })}
              onClick={() => void run("computerCommand", "revoke", device.id)}>{t("Revogar")}</Button>
          </li>)}</ul>}
      </Section>
      <Button disabled={busy} onClick={() => { close(); void run("computerCommand", "stop", ""); }}>{t("Parar acesso")}</Button>
    </>}
    {open && <div className="computer-pairing" role="region" aria-label={t("Conectar celular")}>
      <div className="computer-pairing-header"><h3>{t("Conectar celular")}</h3>
        <Button variant="ghost" onClick={close}>{t("Fechar")}</Button></div>
      {!access?.enabled ? <>
        <p>{t("Ao ativar, este computador aceita os celulares que você parear. O áudio e o texto usam seus modelos e serviços pessoais.")}</p>
        <Button variant="primary" disabled={busy || managed} onClick={() => {
          autoPair.current = true; void run("computerCommand", "enable", "");
        }}>{t("Ativar acesso e gerar QR")}</Button>
      </> : <>
        <p>{t("No Clarify do iPhone, escolha Meu computador e toque em Ler QR do computador. O código funciona uma vez e expira em 5 minutos.")}</p>
        {image && now < expires && <>
          <div className="computer-qr" ref={qrContainer}><img src={image} alt={t("QR para parear o iPhone")} width={256} height={256} /></div>
          <p role="status">{t("Expira em {seconds} s", { seconds: Math.max(0, Math.ceil(expires - now)) })}</p>
        </>}
        {!image && !busy && <p role="status">{t("Gere um novo QR para conectar o celular.")}</p>}
        <Button disabled={busy || !access.running} onClick={pair}>{t("Gerar outro QR")}</Button>
      </>}
      {busy && <p role="status"><LoaderCircle className="spin" size={16} />{t("Carregando…")}</p>}
    </div>}
    {error && <p role="alert" className="error">{t(error)}</p>}
  </Section>;
}
