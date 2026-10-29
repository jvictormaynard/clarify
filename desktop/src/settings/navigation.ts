import { t } from "../i18n";
import {
  Settings2, Mic, Sparkles, Keyboard, Cpu, BookOpen, TextQuote, UserRound, History, Languages, PenLine, Paintbrush, Shield,
} from "lucide-react";

export const getMainPages = () => [
  { id: "dictation", label: t("Ditado"), icon: Mic, group: "workspace" },
  { id: "style", label: t("Estilo"), icon: Paintbrush, group: "workspace" },
  { id: "actions", label: t("Ações de texto"), icon: Sparkles, group: "workspace" },
  { id: "dictionary", label: t("Dicionário"), icon: BookOpen, group: "library" },
  { id: "snippets", label: t("Snippets"), icon: TextQuote, group: "library" },
  { id: "history", label: t("Histórico"), icon: History, group: "library" },
] as const;

export const getSettingsSections = () => [
  { id: "general", label: t("Geral"), icon: Settings2, group: "settings" },
  { id: "models", label: t("Modelos e serviços"), icon: Cpu, group: "settings" },
  { id: "shortcuts", label: t("Atalhos"), icon: Keyboard, group: "settings" },
  { id: "privacy", label: t("Privacidade"), icon: Shield, group: "settings" },
  { id: "account", label: t("Conta Clarify"), icon: UserRound, group: "settings" },
] as const;

export type MainPageId = ReturnType<typeof getMainPages>[number]["id"];
export type SettingsSectionId = ReturnType<typeof getSettingsSections>[number]["id"];

export const isSettingsSection = (id: PageId): id is SettingsSectionId =>
  id === "general" || id === "models" || id === "shortcuts" || id === "privacy" || id === "account";

export const getSettingsPages = () => [
  ...getMainPages(), ...getSettingsSections(),
  {
    id: "text", label: t("Revisão"), icon: Sparkles, group: "processing",
  },
  {
    id: "rewrite", label: t("Reescrita"), icon: PenLine, group: "processing",
  },
  {
    id: "translation", label: t("Tradução"), icon: Languages, group: "processing",
  },
] as const;

export type SettingsPage = ReturnType<typeof getSettingsPages>[number];
export type PageId = SettingsPage["id"];

export function isWorkflowPage(id: PageId) {
  return id === "dictation" || id === "style" || id === "text" || id === "rewrite" || id === "translation";
}

export function isPersonalPage(id: PageId) {
  return id === "models" || id === "text" || id === "rewrite" || id === "translation";
}

export function defaultWorkflowScope(id: PageId) {
  return id === "dictation" ? "transcription" : id === "rewrite" || id === "translation" ? id : "refinement";
}

export function workflowPage(id: PageId, scope: string): PageId {
  return id === "text" && (scope === "rewrite" || scope === "translation") ? scope : id;
}
