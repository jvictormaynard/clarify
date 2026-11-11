import { t } from "../i18n";
import {
  Settings2, Mic, Sparkles, Keyboard, Cpu, BookOpen, TextQuote, UserRound, House, Languages, PenLine, Paintbrush, Shield, Smartphone, Info,
} from "lucide-react";

export const getMainPages = () => [
  { id: "history", label: t("Início"), icon: House, group: "workspace" },
  { id: "dictionary", label: t("Dicionário"), icon: BookOpen, group: "workspace" },
  { id: "snippets", label: t("Snippets"), icon: TextQuote, group: "workspace" },
  { id: "style", label: t("Estilo"), icon: Paintbrush, group: "workspace" },
  { id: "actions", label: t("Ações"), icon: Sparkles, group: "workspace" },
] as const;

export const getSettingsSections = () => [
  { id: "dictation", label: t("Geral"), icon: Mic, group: "settings" },
  { id: "general", label: t("Sistema"), icon: Settings2, group: "settings" },
  { id: "devices", label: t("Dispositivos"), icon: Smartphone, group: "settings" },
  { id: "models", label: t("Modelos e serviços"), icon: Cpu, group: "settings" },
  { id: "shortcuts", label: t("Atalhos"), icon: Keyboard, group: "settings" },
  { id: "privacy", label: t("Dados e privacidade"), icon: Shield, group: "settings" },
  { id: "account", label: t("Conta"), icon: UserRound, group: "settings" },
  { id: "about", label: t("Sobre"), icon: Info, group: "settings" },
] as const;

export type MainPageId = ReturnType<typeof getMainPages>[number]["id"];
export type SettingsSectionId = ReturnType<typeof getSettingsSections>[number]["id"];

export const isSettingsSection = (id: PageId): id is SettingsSectionId =>
  id === "dictation" || id === "general" || id === "devices" || id === "models" || id === "shortcuts" || id === "privacy" || id === "account" || id === "about";

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
