import { uiLanguage } from "../i18n";

const labels = {
  workspace: { en: "Meetings", pt: "Reuniões", es: "Reuniones", de: "Besprechungen", ru: "Встречи" },
  starting: { en: "Starting meeting", pt: "Iniciando reunião", es: "Iniciando reunión", de: "Besprechung startet", ru: "Запуск встречи" },
  recording: { en: "Meeting recording", pt: "Gravando reunião", es: "Grabando reunión", de: "Besprechung wird aufgezeichnet", ru: "Идёт запись встречи" },
  paused: { en: "Meeting paused", pt: "Reunião pausada", es: "Reunión en pausa", de: "Besprechung pausiert", ru: "Запись на паузе" },
  finalizing: { en: "Saving meeting", pt: "Salvando reunião", es: "Guardando reunión", de: "Besprechung wird gespeichert", ru: "Сохранение встречи" },
  interrupted: { en: "Meeting interrupted", pt: "Reunião interrompida", es: "Reunión interrumpida", de: "Besprechung unterbrochen", ru: "Запись встречи прервана" },
  stop: { en: "Stop meeting recording", pt: "Parar gravação da reunião", es: "Detener grabación de la reunión", de: "Aufzeichnung der Besprechung beenden", ru: "Остановить запись встречи" },
} as const;

export type MeetingActivity = Exclude<keyof typeof labels, "workspace" | "stop">;

export function meetingsLabel(key: keyof typeof labels) {
  return labels[key][uiLanguage];
}
