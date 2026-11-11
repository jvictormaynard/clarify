import { t } from "../i18n";
import type { HotkeyDefinition, TextAction } from "./bridge";

export const profileName = (id: string) => t(id === "default" ? "Serviço de texto" : id === "legacy-rewrite" ? "Reescrita" : id === "legacy-translation" ? "Tradução" : id);

export const actionDisplayName = (action: Pick<TextAction, "id" | "name">) =>
  (action.id === "rewrite" && action.name === "Rewrite") || (action.id === "translation" && action.name === "Translation") ? t(action.name) : action.name;

export function hotkeyLabel(value: HotkeyDefinition | null | undefined) {
  if (!value) return "";
  const names: Record<string, string> = { ctrl: "Ctrl", alt: "Alt", shift: "Shift", win: "Win" };
  return [...value.modifiers.map(modifier => names[modifier] ?? modifier), value.key].join("+");
}
