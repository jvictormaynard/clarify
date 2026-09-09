import { Row, Toggle } from "./ui";

export type RecordingControls = {
  max_duration_seconds: number | null;
  warning_seconds: number;
  vad: { enabled: boolean; level_threshold: number; minimum_speech_seconds: number; silence_duration_seconds: number };
};
export type RecordingDraft = { maximum: string; warning: string; enabled: boolean; threshold: string; speech: string; silence: string };
export const recordingDraft = (value: RecordingControls): RecordingDraft => ({
  maximum: value.max_duration_seconds === null ? "" : String(value.max_duration_seconds),
  warning: String(value.warning_seconds), enabled: value.vad.enabled,
  threshold: String(value.vad.level_threshold), speech: String(value.vad.minimum_speech_seconds),
  silence: String(value.vad.silence_duration_seconds),
});
export function recordingValue(draft: RecordingDraft): RecordingControls {
  const number = (value: string, minimum: number, label: string) => {
    const result = Number(value);
    if (!value.trim() || !Number.isFinite(result) || result < minimum) throw new Error(`${label}: informe um número igual ou maior que ${minimum}.`);
    return result;
  };
  const maximum = draft.maximum.trim() === "" ? null : number(draft.maximum, .001, "Duração máxima");
  const warning = number(draft.warning, 0, "Aviso antes do limite");
  const threshold = number(draft.threshold, 0, "Limiar de voz");
  if (threshold > 1) throw new Error("O limiar de voz deve ficar entre 0 e 1.");
  if (maximum !== null && warning > maximum) throw new Error("O aviso não pode ser maior que a duração máxima.");
  return { max_duration_seconds: maximum, warning_seconds: warning, vad: {
    enabled: draft.enabled, level_threshold: threshold,
    minimum_speech_seconds: number(draft.speech, 0, "Tempo mínimo de fala"),
    silence_duration_seconds: number(draft.silence, .001, "Tempo de silêncio"),
  } };
}
export function RecordingOptions({ value, onChange }: { value: RecordingDraft; onChange: (value: RecordingDraft) => void }) {
  const input = (key: Exclude<keyof RecordingDraft, "enabled">, title: string, hint?: string, disabled = false) =>
    <Row title={title} hint={hint}><input className="control" aria-label={title} type="number" step="any" min="0" disabled={disabled} value={value[key]} onChange={e => onChange({ ...value, [key]: e.target.value })} /></Row>;
  return <details><summary>Limites e parada automática</summary>
    {input("maximum", "Duração máxima", "Em segundos. Deixe vazio para não definir um limite.")}
    {input("warning", "Aviso antes do limite", "Segundos antes de atingir a duração máxima.")}
    <Toggle title="Parar após fala e silêncio" checked={value.enabled} onChange={enabled => onChange({ ...value, enabled })} />
    {input("threshold", "Limiar de voz", "De 0 a 1. Valores menores detectam sons mais baixos.", !value.enabled)}
    {input("speech", "Tempo mínimo de fala", "Em segundos.", !value.enabled)}
    {input("silence", "Tempo de silêncio", "Segundos de silêncio para encerrar a gravação.", !value.enabled)}
  </details>;
}
