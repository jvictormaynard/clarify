import { t } from "../i18n";
import { useEffect, useState } from "react";
import { Plus, Pencil, X } from "lucide-react";
import type { Snippet } from "../settings/bridge";
import { dictionaryIdentity } from "../settings/dictionary-identity";
import { Button, Input, Switch, TextArea } from "../components/ui";
import { LibraryPageHeader, LibraryToolbar } from "../components/library-page-layout";
import { LibraryEditor } from "../components/library-editor";
import type { SettingsPageProps } from "../settings/use-settings";
import "../styles/libraries.css";

type Editor = { value: Snippet; original: Snippet | null; index: number; context: string };

export function SnippetsPage({ controller }: SettingsPageProps) {
  const entries = controller.snippets ?? controller.state.snippets;
  const [query, setQuery] = useState("");
  const [editor, setEditor] = useState<Editor | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setEditor(current => {
      if (!current?.original || JSON.stringify(current.value) !== JSON.stringify(current.original)) return current;
      const latest = entries.find(entry => dictionaryIdentity(entry.trigger) === dictionaryIdentity(current.original!.trigger));
      return latest && JSON.stringify(latest) !== JSON.stringify(current.original)
        ? { ...current, original: latest, value: { ...latest } } : current;
    });
  }, [entries]);
  const open = (index = -1) => {
    const original = entries[index] ?? null;
    setEditor({ original, index, value: original ? { ...original } : { trigger: "", replacement: "", enabled: true, case_sensitive: false }, context: controller.state.snippetContext });
    setError("");
  };
  const change = (patch: Partial<Snippet>) => {
    setEditor(current => current ? { ...current, value: { ...current.value, ...patch } } : null);
    setError("");
  };
  const apply = () => {
    if (!editor || editor.context !== controller.state.snippetContext) return;
    const value = { ...editor.value, trigger: editor.value.trigger.trim().normalize("NFC") };
    const index = editor.original ? entries.findIndex(entry => dictionaryIdentity(entry.trigger) === dictionaryIdentity(editor.original!.trigger)) : -1;
    // Do not replace a row changed or removed by a refresh while the dialog was open.
    if (editor.original && (index < 0 || JSON.stringify(entries[index]) !== JSON.stringify(editor.original))) {
      setError(t("A entrada mudou. Feche e abra o editor novamente.")); return;
    }
    if (entries.some((entry, row) => row !== index && dictionaryIdentity(entry.trigger) === dictionaryIdentity(value.trigger))) {
      setError(t("Esta frase de ativação já existe.")); return;
    }
    if (!editor.original && entries.length >= 512) { setError(t("O limite é de 512 snippets.")); return; }
    controller.setSnippets(editor.original ? entries.map((entry, row) => row === index ? value : entry) : [...entries, value]);
    if (editor.original && value.case_sensitive !== editor.original.case_sensitive) {
      // Existing flags use the targeted save path, independent of text drafts.
      void controller.setLibraryPreference("snippets", index, "case_sensitive", value.case_sensitive);
    }
    setEditor(null);
  };
  const visible = entries.map((entry, index) => ({ entry, index })).filter(({ entry }) =>
    `${entry.trigger} ${entry.replacement}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  return <section className="library-page">
    <LibraryPageHeader kind="snippets" title={t("Snippets")}>
      <Button variant="primary" onClick={() => open()}><Plus size={16} />{t("Adicionar novo")}</Button>
    </LibraryPageHeader>
    <LibraryToolbar label={t("Buscar snippets")} query={query} onQueryChange={setQuery}
      refreshLabel={t("Atualizar {label}", { label: t("Snippets") })} busy={!!controller.state.accountState?.busy} onRefresh={() => controller.run("refreshLibrary", controller.state.snippetContext)} />
    {(controller.state.accountState?.syncError || controller.state.accountState?.error) && <p className="error" role="alert">{t(controller.state.accountState.syncError || controller.state.accountState.error)}</p>}
    <div className="library-list">
      {visible.map(({ entry, index }) => <div className="library-entry" key={index}>
        <div className="library-entry-copy"><span className="library-entry-name">{entry.trigger}</span>
          <p className="library-entry-detail">{entry.replacement}</p>
        </div>
        <div className="library-entry-actions">
          <Switch label={t("Usar snippet {v0}", { v0: index + 1 })} checked={entry.enabled}
            onChange={enabled => void controller.setLibraryPreference("snippets", index, "enabled", enabled)} />
          <Button variant="ghost" aria-label={t("Editar snippet {v0}", { v0: index + 1 })} onClick={() => open(index)}><Pencil size={16} /></Button>
          <Button variant="ghost" aria-label={t("Remover snippet {v0}", { v0: index + 1 })}
            onClick={() => controller.setSnippets(entries.filter((_, row) => row !== index))}><X size={16} /></Button>
        </div>
      </div>)}
      {!visible.length && <p className="library-empty hint">{entries.length ? t("Nenhum snippet encontrado.") : t("Adicione seu primeiro snippet.")}</p>}
    </div>
    <LibraryEditor registerCloseGuard={controller.registerLibraryCloseGuard}
      dirty={!!editor && JSON.stringify(editor.value) !== JSON.stringify(editor.original ?? { trigger: "", replacement: "", enabled: true, case_sensitive: false })} open={!!editor} snippet={true} title={editor?.original ? t("Editar snippet") : t("Adicionar snippet")}
      error={error} valid={!!editor?.value.trigger.trim() && !!editor?.value.replacement.trim() && editor?.context === controller.state.snippetContext}
      onClose={() => setEditor(null)} onApply={apply}>
      {editor && <>
          <div className="library-field"><label htmlFor="library-trigger">{t("Frase de ativação")}</label>
            <Input id="library-trigger" aria-label={editor.original ? t("Frase do snippet {v0}", { v0: editor.index + 1 }) : t("Nova frase de ativação")} maxLength={256}
              value={editor.value.trigger} onChange={event => change({ trigger: event.target.value })} />
          </div>
          <div className="library-field"><label htmlFor="library-replacement">{t("Texto a inserir")}</label>
            <TextArea id="library-replacement" aria-label={editor.original ? t("Texto do snippet {v0}", { v0: editor.index + 1 }) : t("Novo texto do snippet")} rows={6} maxLength={4096}
              value={editor.value.replacement} onChange={event => change({ replacement: event.target.value })} />
          </div>
          <div className="library-option"><span>{t("Diferenciar maiúsculas e minúsculas")}</span>
            <Switch label={t("Diferenciar maiúsculas e minúsculas")} checked={editor.value.case_sensitive} onChange={case_sensitive => change({ case_sensitive })} />
          </div>
      </>}
    </LibraryEditor>

  </section>;
}
