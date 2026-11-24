import { t } from "../i18n";
import {
  Settings2, Mic, Sparkles, Cpu, BookOpen, TextQuote, UserRound, House, Paintbrush, Shield, Smartphone, Info, NotebookPen,
} from "lucide-react";
import { meetingsLabel } from "../meetings/labels";

export const getMainPages = () => [
  { id: "history", label: t("Início"), icon: House, group: "workspace" },
  { id: "meetings", label: meetingsLabel("workspace"), icon: NotebookPen, group: "workspace" },
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
  { id: "privacy", label: t("Dados e privacidade"), icon: Shield, group: "settings" },
  { id: "account", label: t("Conta"), icon: UserRound, group: "settings" },
  { id: "about", label: t("Sobre"), icon: Info, group: "settings" },
] as const;

export type MainPageId = ReturnType<typeof getMainPages>[number]["id"];
export type SettingsSectionId = ReturnType<typeof getSettingsSections>[number]["id"];

export type SettingsPage = ReturnType<typeof getMainPages>[number] | ReturnType<typeof getSettingsSections>[number];
export type PageId = MainPageId | SettingsSectionId;

export const isSettingsSection = (id: PageId): id is SettingsSectionId =>
  id === "dictation" || id === "general" || id === "devices" || id === "models" || id === "privacy" || id === "account" || id === "about";

export const reviewScopes = ["refinement", "local_asr_refinement"] as const;
export type ReviewScope = typeof reviewScopes[number];
export const dictationModelScopes = ["transcription", ...reviewScopes] as const;

export type ModelsTab = "services" | "transcription" | "review" | "profiles";
export type ModelsView =
  | { tab: "services" | "profiles" }
  | { tab: "transcription"; scope: "transcription" }
  | { tab: "review"; scope: ReviewScope };
