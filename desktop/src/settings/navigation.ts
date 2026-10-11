import {
  Settings2,
  Mic,
  Sparkles,
  Keyboard,
  Cpu,
  BookOpen,
  UserRound,
} from "lucide-react";

export const settingsPages = [
  { id: "account", label: "Conta Clarify", icon: UserRound },
  { id: "general", label: "Geral", icon: Settings2 },
  { id: "dictation", label: "Ditado", icon: Mic },
  { id: "text", label: "Texto", icon: Sparkles },
  { id: "dictionary", label: "Dicionário", icon: BookOpen },
  { id: "shortcuts", label: "Atalhos", icon: Keyboard },
  { id: "models", label: "Modelos e serviços", icon: Cpu },
] as const;

export type PageId = (typeof settingsPages)[number]["id"];
