import { useEffect, useRef, useState, type ReactNode } from "react";
import { FileAudio, LoaderCircle, MoreVertical, Pause, Play, RotateCcw, Trash2, Undo2 } from "lucide-react";
import { startRecordingPlayback, releaseRecordingPlayback } from "../settings/recording-playback";
import { t } from "../i18n";
import { getRecordingAudio, type RecoveryRecording } from "../settings/bridge";
import { Button } from "./ui";
import { Menu, MenuTrigger, MenuPopup, MenuItem, MenuSeparator } from "./primitives/menu";



export function HistoryAudioActions({ recording, busy, canUndo = false, onRetry, onDelete, onUndo, children }: {
  recording: RecoveryRecording; busy: boolean; canUndo?: boolean;
  onRetry: () => void; onDelete: () => void; onUndo: () => void; children?: ReactNode;
}) {
  const audio = useRef<HTMLAudioElement>(null);
  const source = useRef("");
  const request = useRef<AbortController | null>(null);
  const pending = useRef(false);
  const [loading, setLoading] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState("");
  const processing = recording.status === "processing";
  const retryVisible = recording.status !== "complete";
  useEffect(() => {
    const player = audio.current;
    return () => {
      request.current?.abort(); player?.pause();
      if (player) void releaseRecordingPlayback(player).catch(() => {});
      if (source.current) URL.revokeObjectURL(source.current);
    };
  }, []);
  const getSource = async () => {
    if (source.current) return source.current;
    request.current = new AbortController();
    const blob = await getRecordingAudio(recording.id, request.current.signal);
    if (request.current.signal.aborted) throw new DOMException("Aborted", "AbortError");
    source.current = URL.createObjectURL(blob);
    return source.current;
  };
  const useAudio = async (exporting = false) => {
    if (pending.current) return;
    if (!exporting && audio.current && !audio.current.paused) { audio.current.pause(); return; }
    pending.current = true; setLoading(true); setError("");
    try {
      const url = await getSource();
      if (exporting) {
        const link = document.createElement("a");
        link.href = url; link.download = `clarify-${recording.id}`;
        document.body.append(link); link.click(); link.remove();
      } else if (audio.current) {
        if (audio.current.src !== url) audio.current.src = url;
        await startRecordingPlayback(recording.id, audio.current);
      }
    } catch (problem) {
      if (!(problem instanceof DOMException && problem.name === "AbortError")) setError(t("Não foi possível abrir o áudio. Tente novamente."));
    } finally { pending.current = false; setLoading(false); }
  };
  return <>
    <div className="history-audio-actions">
      {retryVisible && <Button variant="ghost" className="history-retry-action" disabled={busy || processing} aria-label={t("Tentar transcrição novamente")} onClick={onRetry}>
        {processing ? <LoaderCircle size={15} className="spin" aria-hidden="true" /> : <RotateCcw size={15} aria-hidden="true" />}
        {t(processing ? "Processando…" : "Tentar novamente")}
      </Button>}
      <Button variant="ghost" size="history-icon" disabled={loading} aria-label={t(playing ? "Pausar áudio" : "Reproduzir áudio")} title={t(playing ? "Pausar áudio" : "Reproduzir áudio")} onClick={() => void useAudio()}>
        {loading ? <LoaderCircle size={16} className="spin" aria-hidden="true" /> : playing ? <Pause size={16} aria-hidden="true" /> : <Play size={16} aria-hidden="true" />}
      </Button>
      {children}
      <Menu>
        <MenuTrigger render={<Button variant="ghost" size="history-icon" aria-label={t("Mais opções")} title={t("Mais opções")} />}><MoreVertical size={16} aria-hidden="true" /></MenuTrigger>
        <MenuPopup>
          <MenuItem disabled={busy || processing || !canUndo} title={t("Mostra a transcrição original neste dispositivo.")} onClick={onUndo}><Undo2 aria-hidden="true" />{t("Desfazer edição de IA")}</MenuItem>
          {!retryVisible && <MenuItem disabled={busy || processing} onClick={onRetry}><RotateCcw aria-hidden="true" />{t("Tentar transcrição novamente")}</MenuItem>}
          <MenuSeparator />
          <MenuItem variant="destructive" disabled={busy || processing} onClick={onDelete}><Trash2 aria-hidden="true" />{t("Excluir transcrição")}</MenuItem>
          <MenuItem disabled={loading} onClick={() => void useAudio(true)}><FileAudio aria-hidden="true" />{t("Extrair áudio")}</MenuItem>
        </MenuPopup>
      </Menu>
      <audio ref={audio} hidden preload="none" onPlay={() => setPlaying(true)} onPause={() => { setPlaying(false); if (audio.current) void releaseRecordingPlayback(audio.current).catch(() => {}); }} onEnded={() => { setPlaying(false); if (audio.current) void releaseRecordingPlayback(audio.current).catch(() => {}); }} onError={() => { setPlaying(false); setError(t("Não foi possível abrir o áudio. Tente novamente.")); }} />
    </div>
    {error && <span className="history-audio-error" role="alert">{error}</span>}
  </>;
}
