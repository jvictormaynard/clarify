import { t, uiLanguage } from "../../i18n";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { ActivityIndicator, Alert, SectionList, Modal, ScrollView, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { SymbolView } from 'expo-symbols';
import Core, { type HistoryEntry } from '../../../modules/clarify-core';
import { Button, Card, EmptyState, ScreenHeader, NavigationRow, TableRow, ui, usePalette, useReducedMotion } from '../../components/ui';
import { report, useClarify } from '../../state/clarify';
import { MicrophoneSwitch } from '../../components/microphone-switch';
import { ClarifyLogo } from '../../components/clarify-logo';

import { groupHistory, historyDayTitle, historyTime } from '../../history';

import { destinationLabel } from '../../processing';
import { RecordButton } from '../../components/record-button';

const timestamp = (value: number) => new Date(value * 1000).toLocaleString(uiLanguage, { dateStyle: 'medium', timeStyle: 'short' });

export default function Home() {
  const c = usePalette();
  const reducedMotion = useReducedMotion();
  const { state, account, activate, refresh, setKeyboardEntry, setKeyboardToken } = useClarify();
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
  const [pageContext, setPageContext] = useState('');
  const currentContext = useRef(account?.historyContext);
  useLayoutEffect(() => { currentContext.current = account?.historyContext; }, [account?.historyContext]);
  const [cursor, setCursor] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [selection, setSelected] = useState<HistoryEntry | null>(null);
  const selected = selection?.context === account?.historyContext ? selection : null;
  const [original, setOriginal] = useState(false);
  const [action, setAction] = useState<'copy' | 'delete' | null>(null);
  const generation = useRef(0);
  const pending = useRef(false);
  const load = useCallback(async (before = '', append = false) => {
    if (append && pending.current) return;
    const id = append ? generation.current : ++generation.current;
    const context = currentContext.current;
    pending.current = true; setLoading(true); setError(false);
    try {
      const page = await Core.getHistory(before);
      if (id !== generation.current || context !== currentContext.current || page.context !== currentContext.current) return;
      setPageContext(page.context);
      setEntries((previous) => append ? [...previous, ...page.entries] : page.entries);
      setCursor(page.nextCursor);
    } catch { if (id === generation.current) setError(true); }
    finally { if (id === generation.current) { pending.current = false; setLoading(false); } }
  }, []);
  useFocusEffect(useCallback(() => {
    void load();
    return () => { generation.current++; pending.current = false; };
  // The native library revision invalidates the focused page, including keyboard dictations.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, state.libraryRevision, account?.historyContext]));
  const remove = (entry: HistoryEntry) => Alert.alert(t("Excluir transcrição?"), account?.mode === 'computer' || entry.localOnly ? t("Este texto será removido do histórico deste iPhone.") : t("Este texto será removido do histórico da sua conta em todos os dispositivos."), [
    { text: t("Cancelar"), style: 'cancel' }, { text: t("Excluir"), style: 'destructive', onPress: () => {
      setAction('delete');
      void Core.deleteHistory(entry.id, entry.localOnly, entry.context).then(async () => { setSelected(null); await refresh(); await load(); }).catch(report).finally(() => setAction(null));
    } },
  ]);
  const sections = groupHistory(pageContext === account?.historyContext ? entries : []);
  const [today, setToday] = useState(() => new Date());
  useEffect(() => {
    const next = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1);
    const timer = setTimeout(() => setToday(new Date()), Math.max(0, next.getTime() - Date.now()));
    return () => clearTimeout(timer);
  }, [today]);
  return <>
    <SectionList style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={[ui.content, { gap: 0 }]} contentInsetAdjustmentBehavior="automatic"
      sections={sections} stickySectionHeadersEnabled={false} keyExtractor={(entry) => `${entry.localOnly ? 'local' : 'account'}:${entry.id}`}
      onEndReached={() => { if (cursor) void load(cursor, true); }} onEndReachedThreshold={0.4}
      ListHeaderComponent={<View testID="app.home" collapsable={false} style={{ gap: 16 }}>
        <ClarifyLogo size={28} />
        <ScreenHeader title={t('Ditado')} />
        <NavigationRow testID="home.destination" title={t(destinationLabel(account))} icon={account?.mode === 'computer' ? 'desktopcomputer' : 'cloud'} onPress={() => router.push('/processing')} />
        <MicrophoneSwitch />
        {account?.mode === 'computer' && <RecordButton />}
        <Text style={[ui.small, { color: c.muted, marginTop: -8 }]}>{state.sessionActive ? t('O Clarify está ativo para receber ditados do teclado.') : t('Ative o Clarify antes de usar o microfone do teclado.')}</Text>
        {state.phase === 'error' && !state.textOperation && state.message && <Text accessibilityRole="alert" style={[ui.body, { color: c.danger }]}>{t(state.message)}</Text>}
      </View>}
      renderSectionHeader={({ section }) => <Text accessibilityRole="header" style={[ui.section, { color: c.text, paddingTop: 16, paddingBottom: 12 }]}>{historyDayTitle(section.date, today, uiLanguage, t("Hoje"))}</Text>}
      renderItem={({ item, index, section }) => <TableRow first={index === 0} last={index === section.data.length - 1}
        accessibilityLabel={`${timestamp(item.createdAt)}. ${item.sourceDevice === 'desktop' ? 'Desktop' : 'Mobile'}. ${item.text}`} onPress={() => { setOriginal(false); setSelected(item); }}>
        <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 16 }}>
          <Text numberOfLines={4} style={[ui.body, { color: c.text, flex: 1 }]}>{item.text}</Text>
          <View style={{ alignItems: 'flex-end', gap: 2 }}>
            <Text style={[ui.small, { color: c.muted, fontVariant: ['tabular-nums'], textAlign: 'right' }]}>{historyTime(item.createdAt, uiLanguage)}</Text>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
              <SymbolView name={item.sourceDevice === 'desktop' ? 'desktopcomputer' : 'iphone'} size={13} tintColor={c.muted} accessible={false} />
              <Text style={[ui.small, { color: c.muted }]}>{item.sourceDevice === 'desktop' ? 'Desktop' : 'Mobile'}</Text>
            </View>
          </View>
        </View>
      </TableRow>}
      ListEmptyComponent={!loading && !error ? <View style={{ paddingTop: 20 }}><EmptyState title={t('Seu histórico está vazio')}
        detail={account?.historyAccount ? t("Seus próximos ditados aparecerão aqui e nos dispositivos conectados à sua conta.") : t("Seus próximos ditados aparecerão aqui. O histórico fica somente neste iPhone.")}>
        </EmptyState></View> : null}
      ListFooterComponent={loading ? <ActivityIndicator style={{ padding: 20 }} /> : error ? <Button onPress={() => void load()}>{t("Tentar carregar novamente")}</Button> : cursor ? <Button onPress={() => void load(cursor, true)}>{t("Carregar mais")}</Button> : null}
    />
    <Modal visible={selected !== null} animationType={reducedMotion ? 'none' : 'slide'} presentationStyle="pageSheet" onRequestClose={() => setSelected(null)}>
      <SafeAreaView style={{ flex: 1, backgroundColor: c.background }}>
        <ScrollView contentContainerStyle={ui.content} keyboardShouldPersistTaps="handled">
          <View style={ui.row}><Text style={[ui.section, { color: c.text }]}>{t("Transcrição")}</Text><Button onPress={() => setSelected(null)}>{t("Fechar")}</Button></View>
          {selected && <>
            <Text style={[ui.small, { color: c.muted }]}>{timestamp(selected.createdAt)}</Text>
            <Card><Text selectable style={[ui.body, { color: c.text }]}>{original ? selected.transcript : selected.text}</Text></Card>
            {selected.rewritten && <Button onPress={() => setOriginal(!original)}>{original ? t("Mostrar texto revisado") : t("Mostrar transcrição original")}</Button>}
            <Button loading={action === 'copy'} disabled={action !== null} onPress={() => { setAction('copy'); void Core.copyText(original ? selected.transcript : selected.text).then(() => Alert.alert('Clarify', t("Texto copiado."))).catch(report).finally(() => setAction(null)); }}>{t("Copiar texto")}</Button>
            <Button loading={action === 'delete'} disabled={action !== null} destructive onPress={() => remove(selected)}>{t("Excluir transcrição")}</Button>
          </>}
        </ScrollView>
      </SafeAreaView>
    </Modal>
  </>;
}
