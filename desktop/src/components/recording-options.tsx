import { t } from "../i18n";
import { Field, Toggle } from "./ui";
import type { RecordingDraft } from "../settings/recording";

export function RecordingOptions({
  value,
  onChange,
}: {
  value: RecordingDraft;
  onChange: (value: RecordingDraft) => void;
}) {
  const input = (
    key: Exclude<keyof RecordingDraft, "enabled">,
    title: string,
    hint?: string,
    disabled = false,
  ) => (
    <Field
      title={title}
      hint={hint}
      type="number"
      step="any"
      min="0"
      disabled={disabled}
      value={value[key]}
      onChange={(e) => onChange({ ...value, [key]: e.target.value })}
    />
  );
  return (
    <details>
      <summary>{t("Limites e parada automática")}</summary>
      {input(
        "maximum",
        t("Duração máxima"),
        t("Em segundos. Deixe vazio para não definir um limite."),
      )}
      {input(
        "warning",
        t("Aviso antes do limite"),
        t("Segundos antes de atingir a duração máxima."),
      )}
      <Toggle
        title={t("Parar após fala e silêncio")}
        checked={value.enabled}
        onChange={(enabled) => onChange({ ...value, enabled })}
      />
      {input(
        "threshold",
        t("Limiar de voz"),
        t("De 0 a 1. Valores menores detectam sons mais baixos."),
        !value.enabled,
      )}
      {input("speech", t("Tempo mínimo de fala"), t("Em segundos."), !value.enabled)}
      {input(
        "silence",
        t("Tempo de silêncio"),
        t("Segundos de silêncio para encerrar a gravação."),
        !value.enabled,
      )}
    </details>
  );
}
