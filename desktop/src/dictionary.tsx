import { useState } from "react";
import { Plus, Search, X } from "lucide-react";
import type { DictionaryEntry } from "./bridge";
import * as Switch from "@radix-ui/react-switch";

export function Dictionary({ entries, onChange }: {
  entries: DictionaryEntry[]; onChange: (entries: DictionaryEntry[]) => void;
}) {
  const [term, setTerm] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const add = () => {
    const value = term.trim().normalize("NFC");
    if (!value) return;
    if (entries.some(entry => entry.term.toLocaleLowerCase() === value.toLocaleLowerCase())) {
      setError("Este termo já está no dicionário."); return;
    }
    if (entries.length >= 512) { setError("O limite é de 512 termos."); return; }
    onChange([...entries, { term: value, aliases: [], pronunciation: "", enabled: true }]);
    setTerm(""); setQuery(""); setError("");
  };
  const update = (index: number, patch: Partial<DictionaryEntry>) => onChange(entries.map((entry, i) => i === index ? { ...entry, ...patch } : entry));
  const visible = entries.map((entry, index) => ({ entry, index })).filter(({ entry, index }) =>
    index === editing || [entry.term, entry.pronunciation, ...entry.aliases].join(" ").toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  return <section className="dictionary">
    <p className="hint">Nomes e termos que você usa. Escreva como devem aparecer na transcrição.</p>
    <div className="dictionary-add">
      <input className="control" aria-label="Novo termo" placeholder="Railway, pill ou Eva Desktop…" maxLength={256} value={term} onChange={e => { setTerm(e.target.value); setError(""); }} onKeyDown={e => { if (e.key === "Enter" && !e.nativeEvent.isComposing) { e.preventDefault(); add(); } }} />
      <button className="button" aria-label="Adicionar termo" disabled={!term.trim()} onClick={add}><Plus size={18} /></button>
    </div>
    {error && <p className="error" role="alert">{error}</p>}
    {entries.length > 0 && <div className="dictionary-search"><Search size={16} aria-hidden="true" /><input aria-label="Buscar termos" placeholder="Buscar termos" value={query} onChange={e => setQuery(e.target.value)} /><span className="hint">{entries.length}/512</span></div>}
    <div className="dictionary-list">
      {visible.map(({ entry, index }) => <div className="dictionary-entry" key={index}>
        <div className="dictionary-line">
          <input className="control dictionary-term" aria-label={`Termo ${index + 1}`} maxLength={256} value={entry.term} onFocus={() => setEditing(index)} onBlur={() => setEditing(null)} onChange={e => update(index, { term: e.target.value })} />
          <Switch.Root className="switch" aria-label={`Usar termo ${index + 1}`} checked={entry.enabled} onCheckedChange={enabled => update(index, { enabled })}><Switch.Thumb className="switch-thumb" /></Switch.Root>
          <button className="button ghost" aria-label={`Remover termo ${index + 1}`} onClick={() => onChange(entries.filter((_, i) => i !== index))}><X size={16} /></button>
        </div>
        <details><summary>Pronúncia e variações</summary>
          <input className="control" aria-label={`Pronúncia do termo ${index + 1}`} placeholder="Pronúncia (opcional)" maxLength={256} value={entry.pronunciation} onChange={e => update(index, { pronunciation: e.target.value })} />
          <input className="control" aria-label={`Variações do termo ${index + 1}`} placeholder="Variações separadas por vírgula (opcional)" value={entry.aliases.join(",")} onChange={e => update(index, { aliases: e.target.value.split(",") })} />
          <p className="hint">Referências para o reconhecimento, não regras de substituição.</p>
        </details>
      </div>)}
      {!visible.length && <p className="hint dictionary-empty">{entries.length ? "Nenhum termo encontrado." : "Adicione seu primeiro termo acima."}</p>}
    </div>
    <details className="dictionary-help"><summary>Como funciona</summary><p className="hint">O vocabulário orienta modelos de transcrição compatíveis e a revisão, quando ativada. Não treina o modelo nem garante a grafia. No modo local, fica no dispositivo; em serviços na nuvem, os termos usados como contexto são enviados ao serviço. Listas longas podem exceder o contexto: priorize os termos mais importantes no início.</p></details>
  </section>;
}
