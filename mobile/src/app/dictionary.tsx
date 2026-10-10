import { useEffect, useState } from 'react';
import { useIsFocused } from 'expo-router';
import { Alert, FlatList, Modal, Pressable, ScrollView, Switch, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Core, { type VocabularyEntry } from '../../modules/clarify-core';
import { Button, Card, Title, ui, usePalette } from '../components/ui';
import { isBusy, report, useClarify } from '../state/clarify';

const empty = (): VocabularyEntry => ({ term: '', pronunciation: '', aliases: [], enabled: true });
export default function Dictionary() {
  const c = usePalette();
  const focused = useIsFocused();
  const { state, refresh } = useClarify();
  const [entries, setEntries] = useState<VocabularyEntry[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<{ index: number; value: VocabularyEntry } | null>(null);
  const [aliases, setAliases] = useState('');
  const [saving, setSaving] = useState(false);
  const busy = isBusy(state) || saving;
  useEffect(() => {
    if (!focused) return;
    let active = true;
    void Core.getDictionary().then((values) => { if (active) { setEntries(values); setLoaded(true); } }).catch(report);
    return () => { active = false; };
  }, [focused, state.libraryRevision]);
  const edit = (index = -1) => { const value = index < 0 ? empty() : { ...entries[index] }; setAliases(value.aliases.join(', ')); setEditing({ index, value }); };
  async function save(values: VocabularyEntry[]) {
    setSaving(true);
    try { await Core.saveDictionary(values); setEntries(await Core.getDictionary()); setEditing(null); await refresh(); }
    catch (error) { report(error); }
    finally { setSaving(false); }
  }
  function commit() {
    if (!editing) return;
    const value = { ...editing.value, aliases: aliases.split(',').map((s) => s.trim()).filter(Boolean) };
    const values = [...entries];
    if (editing.index < 0) values.push(value); else values[editing.index] = value;
    void save(values);
  }
  const field = (label: string, value: string, change: (value: string) => void, placeholder: string) => <View style={{ gap: 8 }}><Text style={[ui.body, { color: c.text }]}>{label}</Text><TextInput accessibilityLabel={label} value={value} onChangeText={change} editable={!busy} autoCorrect={false} placeholder={placeholder} placeholderTextColor={c.muted} maxLength={label === 'Variações' ? 8192 : 256} style={[ui.input, { color: c.text, borderColor: c.line }]} /></View>;
  return <>
    <FlatList style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={ui.content} contentInsetAdjustmentBehavior="automatic" keyboardShouldPersistTaps="handled"
      data={entries.map((entry, index) => ({ entry, index })).filter(({ entry }) => [entry.term, entry.pronunciation, ...entry.aliases].join(' ').toLocaleLowerCase().includes(search.toLocaleLowerCase()))}
      keyExtractor={({ index }) => String(index)}
      ListHeaderComponent={<View style={{ gap: 16, marginBottom: 16 }}>
        <Title subtitle="Adicione nomes e termos que o Clarify deve reconhecer.">Dicionário</Title>
        <TextInput accessibilityLabel="Buscar no dicionário" value={search} onChangeText={setSearch} placeholder="Buscar palavra" placeholderTextColor={c.muted} style={[ui.input, { color: c.text, backgroundColor: c.card, borderColor: c.line }]} />
        <Button disabled={busy || !loaded || entries.length >= 512} onPress={() => edit()}>Adicionar palavra</Button>
      </View>}
      renderItem={({ item: { entry, index } }) => <Pressable accessibilityRole="button" disabled={busy} onPress={() => edit(index)} style={{ marginBottom: 12 }}><Card>
        <View style={ui.row}><Text style={[ui.body, { color: c.text, fontWeight: '600', flex: 1 }]}>{entry.term}</Text><Text style={[ui.small, { color: c.muted }]}>{entry.enabled ? 'Ativa' : 'Desativada'}</Text></View>
        {(entry.pronunciation || entry.aliases.length > 0) && <Text style={[ui.small, { color: c.muted }]}>{[entry.pronunciation, entry.aliases.join(', ')].filter(Boolean).join(' · ')}</Text>}
      </Card></Pressable>}
      ListEmptyComponent={loaded ? <Text style={[ui.body, { color: c.muted }]}>{search ? 'Nenhuma palavra encontrada.' : 'Seu dicionário está vazio. Adicione sua primeira palavra.'}</Text> : <Button onPress={() => void Core.getDictionary().then((values) => { setEntries(values); setLoaded(true); }).catch(report)}>Carregar dicionário</Button>}
      ListFooterComponent={<Text style={[ui.small, { color: c.muted, marginTop: 12 }]}>As palavras ativas ajudam na transcrição e na reescrita. Elas não são inseridas quando você não as diz. Até 512 palavras.</Text>}
    />
    <Modal visible={editing !== null} animationType="slide" presentationStyle="pageSheet" onRequestClose={() => { if (!saving) setEditing(null); }}>
      <SafeAreaView style={{ flex: 1, backgroundColor: c.background }}><ScrollView contentContainerStyle={ui.content} keyboardShouldPersistTaps="handled">
        <View style={ui.row}><Text style={[ui.section, { color: c.text }]}>{editing?.index === -1 ? 'Adicionar palavra' : 'Editar palavra'}</Text><Button disabled={saving} onPress={() => setEditing(null)}>Cancelar</Button></View>
        {editing && <Card>
          {field('Palavra', editing.value.term, (term) => setEditing({ ...editing, value: { ...editing.value, term } }), 'Nome ou termo')}
          {field('Pronúncia', editing.value.pronunciation, (pronunciation) => setEditing({ ...editing, value: { ...editing.value, pronunciation } }), 'Opcional')}
          {field('Variações', aliases, setAliases, 'Separe por vírgulas (opcional)')}
          <View style={ui.row}><Text style={[ui.body, { color: c.text }]}>Usar esta palavra</Text><Switch accessibilityLabel="Usar esta palavra" value={editing.value.enabled} disabled={busy} onValueChange={(enabled) => setEditing({ ...editing, value: { ...editing.value, enabled } })} /></View>
        </Card>}
        <Button disabled={busy || !editing?.value.term.trim()} onPress={commit}>{saving ? 'Salvando…' : 'Salvar palavra'}</Button>
        {editing && editing.index >= 0 && <Button disabled={busy} destructive onPress={() => Alert.alert('Excluir palavra?', editing.value.term, [{ text: 'Cancelar', style: 'cancel' }, { text: 'Excluir', style: 'destructive', onPress: () => void save(entries.filter((_, index) => index !== editing.index)) }])}>Excluir palavra</Button>}
      </ScrollView></SafeAreaView>
    </Modal>
  </>;
}
