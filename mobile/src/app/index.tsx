import { useCallback, useEffect, useRef, useState } from 'react';
import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { ActivityIndicator, Alert, FlatList, Modal, Pressable, ScrollView, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Core, { type HistoryEntry, type Snapshot } from '../../modules/clarify-core';
import { Button, Card, Title, ui, usePalette } from '../components/ui';
import { RecordButton } from '../components/record-button';
import { isBusy, report, useClarify } from '../state/clarify';

const labels: Record<Snapshot['phase'], string> = { idle: 'Sua voz, com clareza.', recording: 'Ouvindo…', locked: 'Gravação travada', transcribing: 'Transcrevendo…', rewriting: 'Reescrevendo…', ready: 'Texto pronto', error: 'Verifique o ditado' };
const timestamp = (value: number) => new Date(value * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });

export default function Home() {
  const c = usePalette();
  const { state, activate, activating, refresh, keyboardEntry, setKeyboardEntry, keyboardToken, setKeyboardToken, accountBusy } = useClarify();
  const params = useLocalSearchParams<{ activate?: string; request?: string; token?: string }>();
  const handled = useRef('');
  useEffect(() => {
    const source = params.activate;
    if (!source || (source !== 'keyboard' && source !== 'activity')) return;
    const id = `${source}:${params.request ?? ''}`;
    if (handled.current === id) return;
    handled.current = id;
    setKeyboardEntry(source === 'keyboard');
    const token = source === 'keyboard' ? params.token : undefined;
    setKeyboardToken(token);
    router.setParams({ activate: undefined, request: undefined, token: undefined });
    void refresh().then(async (next) => {
      if (!next.configured) { router.navigate('/settings'); return; }
      await activate(token);
    }).catch(report);
  }, [params.activate, params.request, params.token, activate, refresh, setKeyboardEntry, setKeyboardToken]);
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [cursor, setCursor] = useState<number | undefined>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [selected, setSelected] = useState<HistoryEntry | null>(null);
  const [original, setOriginal] = useState(false);
  const generation = useRef(0);
  const pending = useRef(false);
  const load = useCallback(async (before = 0, append = false) => {
    if (append && pending.current) return;
    const id = append ? generation.current : ++generation.current;
    pending.current = true; setLoading(true); setError(false);
    try {
      const page = await Core.getHistory(before);
      if (id !== generation.current) return;
      setEntries((previous) => append ? [...previous, ...page.entries] : page.entries);
      setCursor(page.nextCursor);
    } catch { if (id === generation.current) setError(true); }
    finally { if (id === generation.current) { pending.current = false; setLoading(false); } }
  }, []);
  useFocusEffect(useCallback(() => {
    void load();
    return () => { generation.current++; pending.current = false; };
  // The native library revision invalidates the focused page, including keyboard dictations.
  }, [load, state.libraryRevision]));
  const remove = (entry: HistoryEntry) => Alert.alert('Excluir transcrição?', 'Este texto será removido do histórico deste iPhone.', [
    { text: 'Cancelar', style: 'cancel' }, { text: 'Excluir', style: 'destructive', onPress: () => {
      void Core.deleteHistory(entry.id).then(async () => { setSelected(null); await refresh(); await load(); }).catch(report);
    } },
  ]);
  const busy = isBusy(state);
  return <>
    <FlatList style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={ui.content} contentInsetAdjustmentBehavior="automatic"
      data={entries} keyExtractor={(entry) => entry.id} onEndReached={() => { if (cursor) void load(cursor, true); }} onEndReachedThreshold={0.4}
      ListHeaderComponent={<View style={{ gap: 16, marginBottom: 16 }}>
        <Title subtitle="Fale. O Clarify transcreve e revisa suas palavras.">Boas-vindas ao Clarify</Title>
        <Card>
          <Text style={[ui.section, { color: c.text, textAlign: 'center' }]}>{activating ? 'Ativando microfone…' : keyboardEntry && state.sessionActive && !busy ? 'Microfone ativado' : labels[state.phase]}</Text>
          <Text style={[ui.body, { color: c.muted, textAlign: 'center' }]}>{state.message ?? (keyboardEntry && state.sessionActive && !busy ? 'Volte ao aplicativo anterior. O teclado Clarify está pronto para gravar.' : state.sessionActive ? 'Segure para falar. Deslize para cima para travar.' : 'Ative o microfone para ditar aqui ou pelo teclado.')}</Text>
          {state.sessionActive ? <RecordButton /> : <Button disabled={activating || accountBusy} onPress={() => state.configured ? void activate(keyboardToken).catch(report) : router.navigate('/settings')}>{state.configured ? 'Ativar microfone' : 'Configurar processamento'}</Button>}
        </Card>
        <Text accessibilityRole="header" style={[ui.section, { color: c.text }]}>Histórico</Text>
      </View>}
      renderItem={({ item }) => <Pressable accessibilityRole="button" accessibilityLabel={`${timestamp(item.createdAt)}. ${item.text}`} onPress={() => { setOriginal(false); setSelected(item); }} style={({ pressed }) => ({ marginBottom: 12, opacity: pressed ? 0.6 : 1 })}>
        <Card><Text style={[ui.small, { color: c.muted }]}>{timestamp(item.createdAt)}{!item.rewritten ? ' · Transcrição original' : ''}</Text><Text numberOfLines={4} style={[ui.body, { color: c.text }]}>{item.text}</Text></Card>
      </Pressable>}
      ListEmptyComponent={!loading && !error ? <Card><Text style={[ui.body, { color: c.muted }]}>Seus próximos ditados aparecerão aqui. O histórico fica somente neste iPhone.</Text></Card> : null}
      ListFooterComponent={loading ? <ActivityIndicator style={{ padding: 20 }} /> : error ? <Button onPress={() => void load()}>Tentar carregar novamente</Button> : cursor ? <Button onPress={() => void load(cursor, true)}>Carregar mais</Button> : null}
    />
    <Modal visible={selected !== null} animationType="slide" presentationStyle="pageSheet" onRequestClose={() => setSelected(null)}>
      <SafeAreaView style={{ flex: 1, backgroundColor: c.background }}>
        <ScrollView contentContainerStyle={ui.content} keyboardShouldPersistTaps="handled">
          <View style={ui.row}><Text style={[ui.section, { color: c.text }]}>Transcrição</Text><Button onPress={() => setSelected(null)}>Fechar</Button></View>
          {selected && <>
            <Text style={[ui.small, { color: c.muted }]}>{timestamp(selected.createdAt)}</Text>
            <Card><Text selectable style={[ui.body, { color: c.text }]}>{original ? selected.transcript : selected.text}</Text></Card>
            {selected.rewritten && <Button onPress={() => setOriginal(!original)}>{original ? 'Mostrar texto revisado' : 'Mostrar transcrição original'}</Button>}
            <Button onPress={() => void Core.copyText(original ? selected.transcript : selected.text).then(() => Alert.alert('Clarify', 'Texto copiado.')).catch(report)}>Copiar texto</Button>
            <Button destructive onPress={() => remove(selected)}>Excluir transcrição</Button>
          </>}
        </ScrollView>
      </SafeAreaView>
    </Modal>
  </>;
}
