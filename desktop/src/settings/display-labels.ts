import { isMacDesktop } from "../platform";
import { t } from "../i18n";
import type { HotkeyDefinition, TextAction } from "./bridge";

export const profileName = (id: string) => t(id === "default" ? "Serviço de texto" : id === "legacy-rewrite" ? "Reescrita" : id === "legacy-translation" ? "Tradução" : id);

export const actionDisplayName = (action: Pick<TextAction, "id" | "name">) =>
  (action.id === "rewrite" && action.name === "Rewrite") || (action.id === "translation" && action.name === "Translation") ? t(action.name) : action.name;

export function shortcutKeyName(key: string) {
  const names: Record<string, string> = {
    ctrl: "Ctrl", alt: isMacDesktop() ? "Option" : "Alt",
    fn: "Fn", shift: "Shift", win: isMacDesktop() ? "Command" : "Win",
  };
  return names[key.toLowerCase()] || key;
}

export function hotkeyLabel(value: HotkeyDefinition | null | undefined) {
  if (!value) return "";
  return [...value.modifiers, value.key].map(shortcutKeyName).join("+");
}
