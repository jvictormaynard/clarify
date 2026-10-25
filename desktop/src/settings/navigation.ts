import { t } from "../i18n";
import {
  Settings2, Mic, Sparkles, Keyboard, Cpu, BookOpen, TextQuote, UserRound, History,
} from "lucide-react";

export const getSettingsPages = () => [
  {
    id: "account", label: t("Conta Clarify"), icon: UserRound, group: "account",
  },
  {
    id: "history", label: t("Histórico"), icon: History, group: "workspace",
  },
  {
    id: "general", label: t("Geral"), icon: Settings2, group: "settings",
  },
  {
    id: "dictation", label: t("Ditado"), icon: Mic, group: "workspace",
  },
  {
    id: "text", label: t("Texto"), icon: Sparkles, group: "workspace",
  },
  {
    id: "snippets", label: t("Snippets"), icon: TextQuote, group: "library",
  },
  {
    id: "dictionary", label: t("Dicionário"), icon: BookOpen, group: "library",
  },
  {
    id: "shortcuts", label: t("Atalhos"), icon: Keyboard, group: "settings",
  },
  {
    id: "models", label: t("Modelos e serviços"), icon: Cpu, group: "settings",
  },
] as const;

export type SettingsPage = ReturnType<typeof getSettingsPages>[number];
export type PageId = SettingsPage["id"];
