import { t } from "../../i18n";
import { useEffect, useState } from 'react';
import { useIsFocused } from 'expo-router';
import { ActivityIndicator, Alert, FlatList, Modal, Pressable, ScrollView, Switch, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Core, { type VocabularyEntry } from '../../../modules/clarify-core';
import { Button, Card, ModalHeader, TableRow, Title, ui, usePalette } from '../../components/ui';
import { isBusy, report, useClarify } from '../../state/clarify';
import { SnippetsLibrary } from '../../components/snippets-library';

const empty = (): VocabularyEntry => ({ term: '', pronunciation: '', aliases: [], enabled: true });
export default function Dictionary() {
  const c = usePalette();
  const { account } = useClarify();
  const scope = account?.signedIn ? `${account.endpoint}/${account.email}` : 'guest';
  const [tab, setTab] = useState<'words' | 'snippets'>('words');
  return <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.background }}>
    <View style={{ flexDirection: 'row', marginHorizontal: 20, marginTop: 8, marginBottom: 8, padding: 3, borderRadius: 12, backgroundColor: c.line }}>
      {(['words', 'snippets'] as const).map(value => <Pressable key={value} accessibilityRole="tab" accessibilityState={{ selected: tab === value }}
        onPress={() => setTab(value)} style={{ flex: 1, minHeight: 40, alignItems: 'center', justifyContent: 'center', borderRadius: 9, backgroundColor: tab === value ? c.card : 'transparent' }}>
        <Text style={[ui.body, { color: c.text, fontWeight: tab === value ? '600' : '400' }]}>{value === 'words' ? t('Palavras') : t('Snippets')}</Text>
      </Pressable>)}
    </View>
    {tab === 'words' ? <Words key={scope} /> : <SnippetsLibrary key={scope} />}
  </SafeAreaView>;
}

function Words() {
  const c = usePalette();
  const focused = useIsFocused();
  const { state, refresh, account, accountBusy } = useClarify();
  const [entries, setEntries] = useState<VocabularyEntry[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<{ index: number; value: VocabularyEntry; base: VocabularyEntry[] } | null>(null);
  const [aliases, setAliases] = useState('');
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [loading, setLoading] = useState(true);
  const busy = isBusy(state) || saving || accountBusy || !!account?.busy;
  useEffect(() => {
    if (!focused) return;
    let active = true;
    void Core.getDictionary().then((values) => { if (active) { setEntries(values); setLoaded(true); } }).catch(report).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [focused, state.libraryRevision, account?.signedIn, account?.syncEnabled]);
  const edit = (index = -1) => { const value = index < 0 ? empty() : { ...entries[index] }; setAliases(value.aliases.join(', ')); setEditing({ index, value, base: entries }); };
  async function save(values: VocabularyEntry[], remove = false) {
    setSaving(true);
    setDeleting(remove);
    try { await Core.saveDictionary(values, editing?.base ?? entries); setEntries(await Core.getDictionary()); setEditing(null); await refresh(); }
    catch (error) { report(error); }
    finally { setSaving(false); setDeleting(false); }
  }
  function commit() {
    if (!editing) return;
    const value = { ...editing.value, aliases: aliases.split(',').map((s) => s.trim()).filter(Boolean) };
    const values = [...editing.base];
    if (editing.index < 0) values.push(value); else values[editing.index] = value;
    void save(values);
  }
  const visibleEntries = entries.map((entry, index) => ({ entry, index })).filter(({ entry }) =>
    [entry.term, entry.pronunciation, ...entry.aliases].join(' ').toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  const field = (label: string, value: string, change: (value: string) => void, placeholder: string) => <View style={{ gap: 8 }}><Text style={[ui.body, { color: c.text }]}>{label}</Text><TextInput accessibilityLabel={label} value={value} onChangeText={change} editable={!busy} autoCorrect={false} placeholder={placeholder} placeholderTextColor={c.muted} maxLength={label === t("Variações") ? 8192 : 256} style={[ui.input, { color: c.text, borderColor: c.line }]} /></View>;
  return <>
    <FlatList style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={[ui.content, { gap: 0 }]} contentInsetAdjustmentBehavior="automatic" keyboardShouldPersistTaps="handled"
      data={visibleEntries}
      keyExtractor={({ index }) => String(index)}
      ListHeaderComponent={<View style={{ gap: 16, marginBottom: 16 }}>
        <Title subtitle={t("Adicione nomes e termos que o Clarify deve reconhecer.")}>{t("Dicionário")}</Title>
        {account?.syncEnabled && <Text style={[ui.small, { color: c.muted }]}>{t("Dicionário da conta {v0}. As alterações são sincronizadas ao salvar.", { v0: account.email })}</Text>}
        {account?.error && <Text accessibilityRole="alert" style={[ui.small, { color: c.text }]}>{t(account.error)}</Text>}
        <TextInput accessibilityLabel={t("Buscar no dicionário")} value={search} onChangeText={setSearch} placeholder={t("Buscar palavra")} placeholderTextColor={c.muted} style={[ui.input, { color: c.text, backgroundColor: c.card, borderColor: c.line }]} />
        <Button disabled={busy || !loaded || entries.length >= 512} onPress={() => edit()}>{t("Adicionar palavra")}</Button>
      </View>}
      renderItem={({ item: { entry, index }, index: rowIndex }) => <TableRow first={rowIndex === 0} last={rowIndex === visibleEntries.length - 1} disabled={busy} onPress={() => edit(index)}>
        <View style={ui.row}><Text style={[ui.body, { color: c.text, fontWeight: '600', flex: 1 }]}>{entry.term}</Text><Text style={[ui.small, { color: c.muted }]}>{entry.enabled ? t("Ativa") : t("Desativada")}</Text></View>
        {(entry.pronunciation || entry.aliases.length > 0) && <Text style={[ui.small, { color: c.muted }]}>{[entry.pronunciation, entry.aliases.join(', ')].filter(Boolean).join(' · ')}</Text>}
      </TableRow>}
      ListEmptyComponent={loading ? <ActivityIndicator /> : loaded ? <Text style={[ui.body, { color: c.muted }]}>{search ? t("Nenhuma palavra encontrada.") : t("Seu dicionário está vazio. Adicione sua primeira palavra.")}</Text> : <Button onPress={() => { setLoading(true); void Core.getDictionary().then((values) => { setEntries(values); setLoaded(true); }).catch(report).finally(() => setLoading(false)); }}>{t("Carregar dicionário")}</Button>}
      ListFooterComponent={<Text style={[ui.small, { color: c.muted, marginTop: 12 }]}>{t("As palavras ativas ajudam na transcrição e na reescrita. Elas não são inseridas quando você não as diz. Até 512 palavras.")}</Text>}
    />
    <Modal visible={editing !== null} animationType="slide" presentationStyle="pageSheet" onRequestClose={() => { if (!saving) setEditing(null); }}>
      <SafeAreaView style={{ flex: 1, backgroundColor: c.background }}>
        <ModalHeader title={editing?.index === -1 ? t("Adicionar palavra") : t("Editar palavra")} cancelLabel={t("Cancelar")} saveLabel={t("Salvar")}
          onCancel={() => setEditing(null)} onSave={commit} busy={saving} loading={saving && !deleting} disabled={busy || !editing?.value.term.trim()} />
        <ScrollView contentContainerStyle={[ui.content, { paddingTop: 12 }]} keyboardShouldPersistTaps="handled">
        {editing && <Card>
          {field(t("Palavra"), editing.value.term, (term) => setEditing({ ...editing, value: { ...editing.value, term } }), t("Nome ou termo"))}
          {field(t("Pronúncia"), editing.value.pronunciation, (pronunciation) => setEditing({ ...editing, value: { ...editing.value, pronunciation } }), t("Opcional"))}
          {field(t("Variações"), aliases, setAliases, t("Separe por vírgulas (opcional)"))}
          <View style={ui.row}><Text style={[ui.body, { color: c.text }]}>{t("Usar esta palavra")}</Text><Switch accessibilityLabel={t("Usar esta palavra")} value={editing.value.enabled} disabled={busy} onValueChange={(enabled) => setEditing({ ...editing, value: { ...editing.value, enabled } })} /></View>
        </Card>}
        {editing && editing.index >= 0 && <Button loading={deleting} disabled={busy} destructive onPress={() => Alert.alert(t("Excluir palavra?"), editing.value.term, [{ text: t("Cancelar"), style: 'cancel' }, { text: t("Excluir"), style: 'destructive', onPress: () => void save(editing.base.filter((_, index) => index !== editing.index), true) }])}>{t("Excluir palavra")}</Button>}
      </ScrollView></SafeAreaView>
    </Modal>
  </>;
}
