import { t } from "../i18n";
import { useEffect, useState } from "react";
import { Plus, Pencil, X } from "lucide-react";
import type { DictionaryEntry } from "../settings/bridge";
import { dictionaryIdentity } from "../settings/dictionary-identity";
import { Button, Input, Switch } from "../components/ui";
import { LibraryPageHeader, LibraryToolbar } from "../components/library-page-layout";
import { LibraryEditor } from "../components/library-editor";
import type { SettingsPageProps } from "../settings/use-settings";
import "../styles/libraries.css";

type Editor = { value: DictionaryEntry; original: DictionaryEntry | null; index: number; context: string };

export function DictionaryPage({ controller }: SettingsPageProps) {
  const entries = controller.dictionary ?? controller.state.dictionaryEntries;
  const [query, setQuery] = useState("");
  const [editor, setEditor] = useState<Editor | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setEditor(current => {
      if (!current?.original || JSON.stringify(current.value) !== JSON.stringify(current.original)) return current;
      const latest = entries.find(entry => dictionaryIdentity(entry.term) === dictionaryIdentity(current.original!.term));
      return latest && JSON.stringify(latest) !== JSON.stringify(current.original)
        ? { ...current, original: latest, value: { ...latest } } : current;
    });
  }, [entries]);
  const open = (index = -1) => {
    const original = entries[index] ?? null;
    setEditor({ original, index, value: original ? { ...original } : { term: "", pronunciation: "", aliases: [], enabled: true }, context: controller.state.snippetContext });
    setError("");
  };
  const change = (patch: Partial<DictionaryEntry>) => {
    setEditor(current => current ? { ...current, value: { ...current.value, ...patch } } : null);
    setError("");
  };
  const apply = () => {
    if (!editor || editor.context !== controller.state.snippetContext) return;
    const value = { ...editor.value, term: editor.value.term.trim().normalize("NFC") };
    const index = editor.original ? entries.findIndex(entry => dictionaryIdentity(entry.term) === dictionaryIdentity(editor.original!.term)) : -1;
    // Do not replace a row changed or removed by a refresh while the dialog was open.
    if (editor.original && (index < 0 || JSON.stringify(entries[index]) !== JSON.stringify(editor.original))) {
      setError(t("A entrada mudou. Feche e abra o editor novamente.")); return;
    }
    if (entries.some((entry, row) => row !== index && dictionaryIdentity(entry.term) === dictionaryIdentity(value.term))) {
      setError(t("Este termo já está no dicionário.")); return;
    }
    if (!editor.original && entries.length >= 512) { setError(t("O limite é de 512 termos.")); return; }
    controller.setDictionary(editor.original ? entries.map((entry, row) => row === index ? value : entry) : [...entries, value]);
    setEditor(null);
  };
  const visible = entries.map((entry, index) => ({ entry, index })).filter(({ entry }) =>
    [entry.term, entry.pronunciation, ...entry.aliases].join(" ").toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  return <section className="library-page">
    <LibraryPageHeader kind="dictionary" title={t("Dicionário")}>
      <Button variant="primary" onClick={() => open()}><Plus size={16} />{t("Adicionar novo")}</Button>
    </LibraryPageHeader>
    <LibraryToolbar label={t("Buscar termos")} query={query} onQueryChange={setQuery}
      refreshLabel={t("Atualizar {label}", { label: t("Dicionário") })} busy={!!controller.state.accountState?.busy} onRefresh={() => controller.run("refreshLibrary", controller.state.snippetContext)} />
    {(controller.state.accountState?.syncError || controller.state.accountState?.error) && <p className="error" role="alert">{t(controller.state.accountState.syncError || controller.state.accountState.error)}</p>}
    <div className="library-list">
      {visible.map(({ entry, index }) => <div className="library-entry" key={index}>
        <div className="library-entry-copy"><span className="library-entry-name">{entry.term}</span>
          <p className="library-entry-detail">{[entry.pronunciation, entry.aliases.join(", ")].filter(Boolean).join(" · ")}</p>
        </div>
        <div className="library-entry-actions">
          <Switch label={t("Usar termo {v0}", { v0: index + 1 })} checked={entry.enabled}
            onChange={enabled => void controller.setLibraryPreference("dictionary", index, "enabled", enabled)} />
          <Button variant="ghost" aria-label={t("Editar termo {v0}", { v0: index + 1 })} onClick={() => open(index)}><Pencil size={16} /></Button>
          <Button variant="ghost" aria-label={t("Remover termo {v0}", { v0: index + 1 })}
            onClick={() => controller.setDictionary(entries.filter((_, row) => row !== index))}><X size={16} /></Button>
        </div>
      </div>)}
      {!visible.length && <p className="library-empty hint">{entries.length ? t("Nenhum termo encontrado.") : t("Adicione seu primeiro termo.")}</p>}
    </div>
    <LibraryEditor registerCloseGuard={controller.registerLibraryCloseGuard}
      dirty={!!editor && JSON.stringify(editor.value) !== JSON.stringify(editor.original ?? { term: "", pronunciation: "", aliases: [], enabled: true })} open={!!editor} snippet={false} title={editor?.original ? t("Editar termo") : t("Adicionar termo")}
      error={error} valid={!!editor?.value.term.trim() && editor?.context === controller.state.snippetContext}
      onClose={() => setEditor(null)} onApply={apply}>
      {editor && <>
          <div className="library-field"><label htmlFor="library-term">{t("Termo")}</label>
            <Input id="library-term" aria-label={editor.original ? t("Termo {number}", { number: editor.index + 1 }) : t("Novo termo")} maxLength={256}
              value={editor.value.term} onChange={event => change({ term: event.target.value })} />
          </div>
          <div className="library-field"><label htmlFor="library-pronunciation">{t("Pronúncia (opcional)")}</label>
            <Input id="library-pronunciation" aria-label={t("Pronúncia do termo {v0}", { v0: editor.index + 1 })} maxLength={256}
              value={editor.value.pronunciation} onChange={event => change({ pronunciation: event.target.value })} />
          </div>
          <div className="library-field"><label htmlFor="library-aliases">{t("Variações separadas por vírgula (opcional)")}</label>
            <Input id="library-aliases" aria-label={t("Variações do termo {v0}", { v0: editor.index + 1 })}
              value={editor.value.aliases.join(",")} onChange={event => change({ aliases: event.target.value.split(",") })} />
          </div>
      </>}
    </LibraryEditor>

  </section>;
}
