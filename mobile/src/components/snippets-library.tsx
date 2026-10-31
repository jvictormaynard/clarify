import { ComputerLibraryNotice } from './computer-connection';
import { t } from '../i18n';
import { useEffect, useState } from 'react';
import { useIsFocused } from 'expo-router';
import { ActivityIndicator, Alert, FlatList, Modal, ScrollView, Switch, Text, View } from 'react-native';
import { DraftInput } from './draft-input';
import { SafeAreaView } from 'react-native-safe-area-context';
import Core, { type Snippet } from '../../modules/clarify-core';
import { Button, Card, EmptyState, ModalHeader, TableRow, ui, usePalette, useReducedMotion } from './ui';
import { isBusy, report, useClarify } from '../state/clarify';

const empty = (): Snippet => ({ trigger: '', replacement: '', enabled: true, case_sensitive: false });
export function SnippetsLibrary() {
  const c = usePalette();
  const reducedMotion = useReducedMotion();
  const focused = useIsFocused();
  const { state, account, refresh, accountBusy } = useClarify();
  const scope = account?.historyContext ?? 'guest';
  const [entries, setEntries] = useState<Snippet[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [search, setSearch] = useState('');
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<{ index: number; value: Snippet; base: Snippet[]; scope: string } | null>(null);
  const busy = isBusy(state) || accountBusy || !!account?.busy || saving || !!(account?.managed && !account.signedIn);
  useEffect(() => {
    if (!focused || account?.mode === 'computer') return;
    let active = true;
    void Core.getSnippets().then(values => { if (active) { setEntries(values); setLoaded(true); } }).catch(report).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [focused, scope, state.libraryRevision, account?.mode]);
  const edit = (index = -1) => setEditing({ index, value: index < 0 ? empty() : { ...entries[index] }, base: entries, scope });
  async function save(values: Snippet[]) {
    if (!editing || editing.scope !== scope) return;
    setSaving(true);
    try { await Core.saveSnippets(values, editing.base, account?.historyContext ?? ""); setEntries(await Core.getSnippets()); setEditing(null); await refresh(); }
    catch (error) { report(error); }
    finally { setSaving(false); }
  }
  function commit() {
    if (!editing) return;
    const value = { ...editing.value, trigger: editing.value.trigger.trim() };
    const values = [...editing.base];
    if (editing.index < 0) values.push(value); else values[editing.index] = value;
    void save(values);
  }
  const visible = entries.map((entry, index) => ({ entry, index })).filter(({ entry }) =>
    `${entry.trigger} ${entry.replacement}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  if (account?.mode === 'computer') return <View style={[ui.content, { flex: 1, backgroundColor: c.background }]}><ComputerLibraryNotice /></View>;
  return <>
    <FlatList style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={[ui.content, { gap: 0 }]} contentInsetAdjustmentBehavior="automatic" keyboardShouldPersistTaps="handled"
      data={visible} keyExtractor={({ index }) => String(index)}
      ListHeaderComponent={<View style={{ gap: 16, marginBottom: 16 }}>
        <Text style={[ui.small, { color: c.muted }]}>{account?.signedIn
          ? t('Seus snippets são sincronizados entre seus dispositivos.')
          : t('Os snippets deste dispositivo são aplicados localmente.')}</Text>
        {account?.error && <Text accessibilityRole="alert" style={[ui.small, { color: c.text }]}>{t(account.error)}</Text>}
        <DraftInput selectionColor={c.text} accessibilityLabel={t('Buscar snippets')} initialValue={search} onChangeText={setSearch} placeholder={t('Buscar snippets')} placeholderTextColor={c.muted} style={[ui.input, { color: c.text, backgroundColor: c.card, borderColor: c.controlBorder }]} />
        <Button primary disabled={busy || !loaded || entries.length >= 512} onPress={() => edit()}>{t('Adicionar snippet')}</Button>
      </View>}
      renderItem={({ item: { entry, index }, index: row }) => <TableRow first={row === 0} last={row === visible.length - 1} disabled={busy} onPress={() => edit(index)}>
        <View style={ui.row}><Text style={[ui.body, { color: c.text, fontWeight: '600', flex: 1 }]}>{entry.trigger}</Text><Text style={[ui.small, { color: c.muted }]}>{entry.enabled ? t('Ativa') : t('Desativada')}</Text></View>
        <Text numberOfLines={3} style={[ui.small, { color: c.muted }]}>{entry.replacement}</Text>
      </TableRow>}
      ListEmptyComponent={loading ? <ActivityIndicator /> : loaded ? search ? <Text style={[ui.body, { color: c.muted }]}>{t('Nenhum snippet encontrado.')}</Text> : <EmptyState title={t('Adicione seu primeiro snippet.')} detail={t('Diga uma frase para inserir um texto salvo. Use para assinaturas, endereços e respostas frequentes.')}>
        <View style={{ gap: 6, width: '100%', padding: 14, borderRadius: 12, backgroundColor: c.accentSoft }}>
          <Text style={[ui.small, { color: c.muted }]}>{t('minha assinatura')} →</Text>
          <Text style={[ui.body, { color: c.text }]}>{t('Seu nome\nEquipe de suporte')}</Text>
        </View>
      </EmptyState>
        : <Button onPress={() => { setLoading(true); void Core.getSnippets().then(values => { setEntries(values); setLoaded(true); }).catch(report).finally(() => setLoading(false)); }}>{t('Carregar snippets')}</Button>}
      ListFooterComponent={<Text style={[ui.small, { color: c.muted, marginTop: 12 }]}>{t('Com a reescrita ativa, o texto do snippet é enviado à IA como parte da mensagem. Quando você diz apenas a frase de ativação, o texto salvo é inserido sem reescrita.')}</Text>}
    />
    <Modal visible={editing !== null} animationType={reducedMotion ? 'none' : 'slide'} presentationStyle="pageSheet" onRequestClose={() => { if (!saving) setEditing(null); }}>
      <SafeAreaView style={{ flex: 1, backgroundColor: c.background }}>
        <ModalHeader title={editing?.index === -1 ? t('Adicionar snippet') : t('Editar snippet')} cancelLabel={t('Cancelar')} saveLabel={t('Salvar')}
          onCancel={() => setEditing(null)} onSave={commit} busy={saving} loading={saving} disabled={busy || !editing?.value.trigger.trim() || !editing?.value.replacement.trim()} />
        <ScrollView automaticallyAdjustKeyboardInsets contentContainerStyle={[ui.content, { paddingTop: 12 }]} keyboardShouldPersistTaps="handled">
          {editing && <Card>
            <Text style={[ui.body, { color: c.text }]}>{t('Frase de ativação')}</Text>
            <DraftInput selectionColor={c.text} accessibilityLabel={t('Frase de ativação')} initialValue={editing.value.trigger} onChangeText={trigger => setEditing(current => current ? { ...current, value: { ...current.value, trigger } } : null)} editable={!busy} autoCorrect={false} maxLength={256} style={[ui.input, { color: c.text, borderColor: c.controlBorder }]} />
            <Text style={[ui.body, { color: c.text }]}>{t('Texto a inserir')}</Text>
            <DraftInput selectionColor={c.text} accessibilityLabel={t('Texto a inserir')} initialValue={editing.value.replacement} onChangeText={replacement => setEditing(current => current ? { ...current, value: { ...current.value, replacement } } : null)} editable={!busy} multiline maxLength={4096} textAlignVertical="top" style={[ui.input, { color: c.text, borderColor: c.controlBorder, minHeight: 160 }]} />
            <View style={ui.row}><Text style={[ui.body, { color: c.text, flex: 1 }]}>{t('Usar snippet')}</Text><Switch accessibilityLabel={t('Usar snippet')} value={editing.value.enabled} disabled={busy} onValueChange={enabled => setEditing(current => current ? { ...current, value: { ...current.value, enabled } } : null)} /></View>
            <View style={ui.row}><Text style={[ui.body, { color: c.text, flex: 1 }]}>{t('Diferenciar maiúsculas e minúsculas')}</Text><Switch accessibilityLabel={t('Diferenciar maiúsculas e minúsculas')} value={editing.value.case_sensitive} disabled={busy} onValueChange={case_sensitive => setEditing(current => current ? { ...current, value: { ...current.value, case_sensitive } } : null)} /></View>
          </Card>}
          {editing && editing.index >= 0 && <Button disabled={busy} destructive onPress={() => Alert.alert(t('Excluir snippet?'), editing.value.trigger,
            [{ text: t('Cancelar'), style: 'cancel' }, { text: t('Excluir'), style: 'destructive', onPress: () => void save(editing.base.filter((_, index) => index !== editing.index)) }])}>{t('Excluir snippet')}</Button>}
        </ScrollView>
      </SafeAreaView>
    </Modal>
  </>;
}
