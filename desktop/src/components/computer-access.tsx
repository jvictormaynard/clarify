import { useEffect, useRef, useState } from "react";
import { LoaderCircle, Smartphone } from "lucide-react";
import { t } from "../i18n";
import { Button, Row, Section, SettingsDisclosure, Switch } from "./ui";
import { Dialog, DialogPopup, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "./primitives/dialog";
import { call, getComputerPairing } from "../settings/bridge";
import type { SettingsPageProps } from "../settings/use-settings";

const errors: Record<string, string> = {
  unavailable: "O acesso pelo celular não está disponível nesta versão.",
  qr_unavailable: "Não foi possível gerar o QR. Atualize o Clarify e tente novamente.",
  failed: "Não foi possível alterar o acesso do celular. Verifique a conexão e tente novamente.",
};

export function ComputerAccess({ controller }: SettingsPageProps) {
  const { state, run, closing, settingsOpen } = controller;
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
  useEffect(() => { if (closing || managed || !settingsOpen) close(); }, [closing, managed, settingsOpen]);
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
  return <><Section title={t("Acesso pelo celular")}>
    <Row title={t("Conectar celular")}
      hint={managed ? t("Saia da conta Clarify para conectar o celular aos seus modelos e serviços pessoais.")
        : t("Use os modelos deste computador no iPhone.")}>
      <Button variant={!access?.devices.length && !open ? "primary" : "default"} disabled={managed || !access || access.error === "unavailable" || access.blocked || busy}
        onClick={() => { setOpen(true); if (access?.running) pair(); }}>
        <Smartphone size={16} />{t("Conectar celular")}
      </Button>
    </Row>
    {access?.enabled && <>
      <p className="hint" role="status">{!access.running ? t("O computador está offline. Pare o acesso e tente novamente.")
        : access.relayConnected ? t("Acesso pela internet ativo.") : t("Acesso disponível na mesma rede Wi-Fi.")}</p>
      {access.running && access.relayConfigured && !access.relayConnected && <p className="hint" role="status">
        {t("Para usar fora do Wi-Fi, abra Conta → Meu computador no iPhone e ative o acesso pela internet.")}
      </p>}
      {access.devices.length > 0 && <p className="hint">{access.devices.length === 1
        ? t("1 celular pareado") : t("{count} celulares pareados", { count: access.devices.length })}</p>}
      <SettingsDisclosure title={t("Dispositivos e opções")}>
      <div className="computer-options-content">
      <Row title={t("Manter acesso ao iniciar o Clarify")}>
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
      </div>
      </SettingsDisclosure>
    </>}
    {error && <p role="alert" className="error">{t(error)}</p>}
  </Section>
  <Dialog open={open} onOpenChange={value => { if (!value) close(); }}>
    <DialogPopup className="max-w-lg" bottomStickOnMobile={false}>
      <DialogHeader><DialogTitle>{t("Conectar celular")}</DialogTitle>
        <DialogDescription>{t("Use os modelos deste computador no iPhone.")}</DialogDescription></DialogHeader>
      <div className="computer-pairing" role="region" aria-label={t("Conectar celular")}>
      {!access?.enabled ? <>
        <p>{t("Permita que os celulares pareados usem os modelos deste PC.")}</p>
        <Button variant="primary" disabled={busy || managed} onClick={() => {
          autoPair.current = true; void run("computerCommand", "enable", "");
        }}>{t("Ativar acesso e gerar QR")}</Button>
      </> : <>
        <p>{t("No iPhone: Clarify → Conta → Meu computador → Ler QR do computador.")}</p>
        <p className="hint">{t("Na primeira conexão, use a mesma rede Wi-Fi.")}</p>
        {image && now < expires && <>
          <div className="computer-qr" ref={qrContainer}><img src={image} alt={t("QR para parear o iPhone")} width={256} height={256} /></div>
          <p role="status">{t("Expira em {seconds} s", { seconds: Math.max(0, Math.ceil(expires - now)) })}</p>
        </>}
        {!image && !busy && <p role="status">{t("Gere um novo QR para conectar o celular.")}</p>}
        <Button disabled={busy || !access.running} onClick={pair}>{t("Gerar outro QR")}</Button>
      </>}
      {busy && <p role="status"><LoaderCircle className="spin" size={16} />{t("Carregando…")}</p>}
      {error && <p role="alert" className="error">{t(error)}</p>}
      </div>
      <DialogFooter><Button onClick={close}>{t("Concluído")}</Button></DialogFooter>
    </DialogPopup>
  </Dialog></>;
}
