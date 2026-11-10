import { t } from "../i18n";
import type { WritingStyle } from "./bridge";

export const writingStyleNames: Record<WritingStyle, string> = {
  natural: "Manter meu tom", formal: "Formal", casual: "Casual",
  very_casual: "Muito casual", informal: "Informal", organized: "Organizado",
};

// Keep a saved legacy value available without offering it for new selections.
export function writingStyleOptions(selected: WritingStyle | "") {
  return ["natural", "formal", "casual", ...(!selected || !["natural", "formal", "casual"].includes(selected) ? [selected] : [])]
    .map(id => ({ id, label: t(id ? writingStyleNames[id as WritingStyle] : "Instruções atuais") }));
}
