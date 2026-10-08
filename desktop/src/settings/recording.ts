export type RecordingControls = {
  max_duration_seconds: number | null;
  warning_seconds: number;
  vad: {
    enabled: boolean;
    level_threshold: number;
    minimum_speech_seconds: number;
    silence_duration_seconds: number;
  };
};
export type RecordingDraft = {
  maximum: string;
  warning: string;
  enabled: boolean;
  threshold: string;
  speech: string;
  silence: string;
};
export const recordingDraft = (value: RecordingControls): RecordingDraft => ({
  maximum:
    value.max_duration_seconds === null
      ? ""
      : String(value.max_duration_seconds),
  warning: String(value.warning_seconds),
  enabled: value.vad.enabled,
  threshold: String(value.vad.level_threshold),
  speech: String(value.vad.minimum_speech_seconds),
  silence: String(value.vad.silence_duration_seconds),
});
export function recordingValue(draft: RecordingDraft): RecordingControls {
  const number = (value: string, minimum: number, label: string) => {
    const result = Number(value);
    if (!value.trim() || !Number.isFinite(result) || result < minimum)
      throw new Error(
        `${label}: informe um número igual ou maior que ${minimum}.`,
      );
    return result;
  };
  const maximum =
    draft.maximum.trim() === ""
      ? null
      : number(draft.maximum, 0.001, "Duração máxima");
  const warning = number(draft.warning, 0, "Aviso antes do limite");
  const threshold = number(draft.threshold, 0, "Limiar de voz");
  if (threshold > 1) throw new Error("O limiar de voz deve ficar entre 0 e 1.");
  if (maximum !== null && warning > maximum)
    throw new Error("O aviso não pode ser maior que a duração máxima.");
  return {
    max_duration_seconds: maximum,
    warning_seconds: warning,
    vad: {
      enabled: draft.enabled,
      level_threshold: threshold,
      minimum_speech_seconds: number(draft.speech, 0, "Tempo mínimo de fala"),
      silence_duration_seconds: number(
        draft.silence,
        0.001,
        "Tempo de silêncio",
      ),
    },
  };
}
