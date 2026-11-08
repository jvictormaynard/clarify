import { t } from "../i18n";
import { useState } from "react";
import { Plus, Search, X } from "lucide-react";
import type { DictionaryEntry } from "../settings/bridge";
import { Button, Input, SettingsDisclosure, Switch } from "../components/ui";
import type { SettingsPageProps } from "../settings/use-settings";

export function DictionaryPage({ controller }: SettingsPageProps) {
  const entries = controller.dictionary ?? controller.state.dictionaryEntries;
  const onChange = controller.setDictionary;
  const [term, setTerm] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const add = () => {
    const value = term.trim().normalize("NFC");
    if (!value) return;
    if (
      entries.some(
        (entry) => entry.term.toLocaleLowerCase() === value.toLocaleLowerCase(),
      )
    ) {
      setError(t("Este termo já está no dicionário."));
      return;
    }
    if (entries.length >= 512) {
      setError(t("O limite é de 512 termos."));
      return;
    }
    onChange([
      ...entries,
      { term: value, aliases: [], pronunciation: "", enabled: true },
    ]);
    setTerm("");
    setQuery("");
    setError("");
  };
  const update = (index: number, patch: Partial<DictionaryEntry>) =>
    onChange(
      entries.map((entry, i) => (i === index ? { ...entry, ...patch } : entry)),
    );
  const visible = entries
    .map((entry, index) => ({ entry, index }))
    .filter(
      ({ entry, index }) =>
        index === editing ||
        [entry.term, entry.pronunciation, ...entry.aliases]
          .join(" ")
          .toLocaleLowerCase()
          .includes(query.toLocaleLowerCase()),
    );
  return (
    <section className="dictionary">
      <p className="hint">{controller.state.accountState?.syncEnabled ? t("Dicionário da conta {v0}. As alterações são sincronizadas ao salvar.", { v0: controller.state.accountState.email }) : t("Dicionário deste computador.")}</p>
      <p className="hint">{t("Nomes e termos que você usa. Escreva como devem aparecer na transcrição.")}</p>
      <div className="dictionary-add">
        <Input
          aria-label={t("Novo termo")}
          placeholder={t("Railway, pill ou Eva Desktop…")}
          maxLength={256}
          value={term}
          onChange={(e) => {
            setTerm(e.target.value);
            setError("");
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) {
              e.preventDefault();
              add();
            }
          }}
        />
        <Button
          aria-label={t("Adicionar termo")}
          disabled={!term.trim()}
          onClick={add}
        >
          <Plus size={18} />
        </Button>
      </div>
      {error && (
        <p className="error" role="alert">
          {t(error)}
        </p>
      )}
      {entries.length > 0 && (
        <div className="dictionary-search">
          <Search size={16} aria-hidden="true" />
          <Input unstyled className="library-search-input"
            aria-label={t("Buscar termos")}
            placeholder={t("Buscar termos")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <span className="hint">{t("{v0}/512", { v0: entries.length })}</span>
        </div>
      )}
      <div className="dictionary-list">
        {visible.map(({ entry, index }) => (
          <div className="dictionary-entry" key={index}>
            <div className="dictionary-line">
              <Input
                className="dictionary-term"
                aria-label={t("Termo {number}", { number: index + 1 })}
                maxLength={256}
                value={entry.term}
                onFocus={() => setEditing(index)}
                onBlur={() => setEditing(null)}
                onChange={(e) => update(index, { term: e.target.value })}
              />
              <Switch
                label={t("Usar termo {number}", { number: index + 1 })}
                checked={entry.enabled}
                onChange={(enabled) => void controller.setLibraryPreference("dictionary", index, "enabled", enabled)}
              />
              <Button
                variant="ghost"
                aria-label={t("Remover termo {number}", { number: index + 1 })}
                onClick={() => onChange(entries.filter((_, i) => i !== index))}
              >
                <X size={16} />
              </Button>
            </div>
            <SettingsDisclosure title={t("Pronúncia e variações")}>
              <Input
                aria-label={t("Pronúncia do termo {v0}", { v0: index + 1 })}
                placeholder={t("Pronúncia (opcional)")}
                maxLength={256}
                value={entry.pronunciation}
                onChange={(e) =>
                  update(index, { pronunciation: e.target.value })
                }
              />
              <Input
                aria-label={t("Variações do termo {v0}", { v0: index + 1 })}
                placeholder={t("Variações separadas por vírgula (opcional)")}
                value={entry.aliases.join(",")}
                onChange={(e) =>
                  update(index, { aliases: e.target.value.split(",") })
                }
              />
              <p className="hint">{t("Referências para o reconhecimento, não regras de substituição.")}</p>
            </SettingsDisclosure>
          </div>
        ))}
        {!visible.length && (
          <p className="hint dictionary-empty">
            {entries.length
              ? t("Nenhum termo encontrado.")
              : t("Adicione seu primeiro termo acima.")}
          </p>
        )}
      </div>
      <SettingsDisclosure className="dictionary-help" title={t("Como funciona")}>
        <p className="hint">{t("O vocabulário orienta modelos de transcrição compatíveis e a revisão, quando ativada. Não treina o modelo nem garante a grafia. No modo local, fica no dispositivo; em serviços na nuvem, os termos usados como contexto são enviados ao serviço. Listas longas podem exceder o contexto: priorize os termos mais importantes no início.")}</p>
      </SettingsDisclosure>
    </section>
  );
}
