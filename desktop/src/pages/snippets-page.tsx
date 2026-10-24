import { t } from "../i18n";
import { useEffect, useState } from "react";
import { Plus, Search, X } from "lucide-react";
import { Button, Input, Switch, TextArea } from "../components/ui";
import type { Snippet } from "../settings/bridge";
import type { SettingsPageProps } from "../settings/use-settings";
import "../styles/snippets.css";

export function SnippetsPage({ controller }: SettingsPageProps) {
  const entries = controller.snippets ?? controller.state.snippets;
  const [trigger, setTrigger] = useState("");
  const [replacement, setReplacement] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  useEffect(() => {
    if (controller.snippets === null) {
      setTrigger("");
      setReplacement("");
      setError("");
    }
  }, [controller.snippets]);
  const add = () => {
    const phrase = trigger.trim().normalize("NFC");
    if (!phrase || !replacement.trim()) return;
    if (entries.some((entry) => entry.trigger.toLocaleLowerCase() === phrase.toLocaleLowerCase())) {
      setError(t("Esta frase de ativação já existe."));
      return;
    }
    if (entries.length >= 512) {
      setError(t("O limite é de 512 snippets."));
      return;
    }
    controller.setSnippets([...entries, {
      trigger: phrase, replacement, enabled: true, case_sensitive: false,
    }]);
    setTrigger("");
    setReplacement("");
    setQuery("");
    setError("");
  };
  const update = (index: number, patch: Partial<Snippet>) =>
    controller.setSnippets(entries.map((entry, i) => i === index ? { ...entry, ...patch } : entry));
  const visible = entries.map((entry, index) => ({ entry, index })).filter(
    ({ entry, index }) => index === editing ||
      `${entry.trigger} ${entry.replacement}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
  );

  return (
    <section className="snippets">
      <p className="hint">
        {t("Diga uma frase para inserir um texto salvo. Use para assinaturas, endereços e respostas frequentes.")}
      </p>
      <form className="snippet-composer" onSubmit={(event) => { event.preventDefault(); add(); }}
        onKeyDown={(event) => {
          if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) {
            event.preventDefault(); add();
          }
        }}>
        <label htmlFor="new-snippet-trigger">{t("Frase de ativação")}</label>
        <Input id="new-snippet-trigger" aria-label={t("Nova frase de ativação")}
          placeholder={t("minha assinatura")} maxLength={256} value={trigger}
          onChange={(event) => { setTrigger(event.target.value); setError(""); }} />
        <label htmlFor="new-snippet-text">{t("Texto a inserir")}</label>
        <TextArea id="new-snippet-text" aria-label={t("Novo texto do snippet")}
          placeholder={t("Seu nome\nEquipe de suporte")} rows={3} maxLength={4096}
          value={replacement} onChange={(event) => setReplacement(event.target.value)} />
        <div className="snippet-actions">
          <span className="hint">{replacement.length}/4096</span>
          <Button type="submit" disabled={!trigger.trim() || !replacement.trim()}>
            <Plus size={16} /> {t("Adicionar snippet")}
          </Button>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
      </form>
      {entries.length > 0 && (
        <div className="dictionary-search">
          <Search size={16} aria-hidden="true" />
          <input aria-label={t("Buscar snippets")} placeholder={t("Buscar snippets")} value={query}
            onChange={(event) => setQuery(event.target.value)} />
          <span className="hint">{entries.length}/512</span>
        </div>
      )}
      <div className="snippet-list">
        {visible.map(({ entry, index }) => (
          <div className="snippet-entry" key={index}
            onFocus={() => setEditing(index)}
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget)) setEditing(null);
            }}>
            <div className="dictionary-line">
              <label htmlFor={`snippet-trigger-${index}`} className="snippet-label">{t("Frase de ativação")}</label>
              <Switch label={t("Usar snippet {v0}", { v0: index + 1 })} checked={entry.enabled}
                onChange={(enabled) => update(index, { enabled })} />
              <Button variant="ghost" aria-label={t("Remover snippet {v0}", { v0: index + 1 })}
                onClick={() => controller.setSnippets(entries.filter((_, i) => i !== index))}>
                <X size={16} />
              </Button>
            </div>
            <Input id={`snippet-trigger-${index}`} aria-label={t("Frase do snippet {v0}", { v0: index + 1 })}
              maxLength={256} value={entry.trigger}
              onChange={(event) => update(index, { trigger: event.target.value })} />
            <label htmlFor={`snippet-text-${index}`}>{t("Texto a inserir")}</label>
            <TextArea id={`snippet-text-${index}`} aria-label={t("Texto do snippet {v0}", { v0: index + 1 })}
              rows={3} maxLength={4096} value={entry.replacement}
              onChange={(event) => update(index, { replacement: event.target.value })} />
            <details>
              <summary>{t("Opções de correspondência")}</summary>
              <div className="snippet-actions">
                <span className="hint">{t("Diferenciar maiúsculas e minúsculas")}</span>
                <Switch label={t("Diferenciar maiúsculas no snippet {v0}", { v0: index + 1 })}
                  checked={entry.case_sensitive}
                  onChange={(case_sensitive) => update(index, { case_sensitive })} />
              </div>
            </details>
          </div>
        ))}
        {!visible.length && <p className="hint dictionary-empty">
          {entries.length ? t("Nenhum snippet encontrado.") : t("Adicione seu primeiro snippet acima.")}
        </p>}
      </div>
      <details className="dictionary-help">
        <summary>{t("Como funciona")}</summary>
        <p className="hint">
          {t("Diga a frase sozinha para inserir o texto exato. Dentro de uma mensagem, o texto é inserido antes da reescrita e pode ser ajustado. Use Salvar para aplicar ou Descartar para cancelar.")}
        </p>
        <p className="hint">
          {controller.state.accountState?.signedIn
            ? t("Os snippets desta conta são sincronizados e aplicados pelo servidor no desktop e no mobile.")
            : t("Os snippets deste dispositivo são aplicados localmente.")}
          {" "}{t("Com a reescrita ativa, o texto do snippet é enviado à IA como parte da mensagem. Quando você diz apenas a frase de ativação, o texto salvo é inserido sem reescrita.")}
        </p>
      </details>
    </section>
  );
}
