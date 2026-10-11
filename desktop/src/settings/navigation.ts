import { t } from "../i18n";
import {
  Settings2,
  Mic,
  Sparkles,
  Keyboard,
  Cpu,
  BookOpen,
  UserRound,
} from "lucide-react";

export const getSettingsPages = () => [
  { id: "account", label: t("Conta Clarify"), icon: UserRound },
  { id: "general", label: t("Geral"), icon: Settings2 },
  { id: "dictation", label: t("Ditado"), icon: Mic },
  { id: "text", label: t("Texto"), icon: Sparkles },
  { id: "dictionary", label: t("Dicionário"), icon: BookOpen },
  { id: "shortcuts", label: t("Atalhos"), icon: Keyboard },
  { id: "models", label: t("Modelos e serviços"), icon: Cpu },
] as const;

export type PageId = ReturnType<typeof getSettingsPages>[number]["id"];
