import { t } from "../i18n";
import type { PageId, SettingsPage } from "./navigation";

export type SettingsSearchResult = { id: string; page: SettingsPage; title: string; target?: string };

// Index stable sections only. Provider choices and account data remain in the
// existing local filters and never enter the navigation index.
const sections: Partial<Record<PageId, readonly string[]>> = {
  general: ["Preferências"],
  dictation: ["Revisão do ditado", "Estilos por aplicativo", "Entrada de áudio"],
  shortcuts: ["Ações rápidas"],
};
const aliases: Partial<Record<PageId, readonly string[]>> = {
  general: ["Idioma do texto", "Iniciar com o Windows", "Atualizações"],
  dictation: ["Microfone", "Nível de revisão", "Modo de gravação"],
  dictionary: ["Novo termo", "Vocabulário"],
  snippets: ["Nova frase de ativação", "Novo texto do snippet"],
  text: ["Instruções", "Tradução", "Reescrita"],
  models: ["Whisper local", "Serviços", "Chave de API"],
};
const normalize = (value: string) => value.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();

export function searchSettings(query: string, pages: readonly SettingsPage[]): SettingsSearchResult[] {
  const words = normalize(query.trim()).split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  return pages.flatMap<SettingsSearchResult>(page => {
    const pageResult = { id: page.id, page, title: page.label };
    const matchedSections = (sections[page.id] ?? []).flatMap((source, index) => {
      const title = t(source);
      return words.every(word => normalize(`${title} ${page.label}`).includes(word))
        ? [{ id: `${page.id}-${index}`, page, title, target: title }] : [];
    });
    const pageMatches = words.every(word => normalize([
      page.label, ...(aliases[page.id] ?? []).map(source => t(source)),
    ].join(" ")).includes(word));
    return matchedSections.length ? matchedSections : pageMatches ? [pageResult] : [];
  });
}
