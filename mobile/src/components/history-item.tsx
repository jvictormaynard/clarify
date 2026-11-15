import { useRef, useState, type ReactNode } from 'react';
import { requireNativeView } from 'expo';
import { Alert, Pressable, Text, View, type NativeSyntheticEvent, type ViewProps } from 'react-native';
import { SymbolView } from 'expo-symbols';
import Core, { type HistoryEntry } from '../../modules/clarify-core';
import { t, uiLanguage } from '../i18n';
import { historyTime } from '../history';
import { isBusy, report, useClarify } from '../state/clarify';
import { TableRow, ui, usePalette } from './ui';

type MenuAction = { id: string; title: string; systemImage: string; disabled: boolean; destructive?: boolean };
const ContextMenu = requireNativeView<ViewProps & {
  menuID: string; actions: MenuAction[]; children: ReactNode;
  onAction: (event: NativeSyntheticEvent<{ id: string; menuID: string }>) => void;
}>('ClarifyCore', 'HistoryContextMenu');

type Item = HistoryEntry & { audioOnly?: boolean };
export function HistoryItem({ entry, first, last, onOpen, onDelete }: {
  entry: Item; first: boolean; last: boolean; onOpen: () => void; onDelete: () => void;
}) {
  const c = usePalette();
  const { state, account, accountBusy, refresh } = useClarify();
  const [action, setAction] = useState('');
  const pending = useRef(false);
  const recording = entry.recording;
  const busy = !!action || isBusy(state) || accountBusy || !!account?.busy || !!recording?.processing;
  const playing = !!recording && state.playingRecordingID === recording.id;
  const failed = !!recording && recording.status !== 'complete' && !recording.processing;
  const menuID = JSON.stringify([entry.context, entry.localOnly, entry.id]);
  async function perform(name: string, operation: () => Promise<unknown>) {
    if (pending.current || entry.context !== (account?.historyContext ?? '')) return;
    pending.current = true; setAction(name);
    try { await operation(); await refresh(); }
    catch (error) { report(error); }
    finally { pending.current = false; setAction(''); }
  }
  const retry = () => { if (recording && !busy && state.configured) void perform('retry', () => Core.reprocessRecording(recording.id, entry.context)); };
  const remove = () => {
    if (!entry.audioOnly) { onDelete(); return; }
    if (!recording) return;
    Alert.alert(t('Excluir transcrição?'), t('Esta ação remove o áudio salvo deste iPhone.'), [
      { text: t('Cancelar'), style: 'cancel' },
      { text: t('Excluir'), style: 'destructive', onPress: () => { void perform('delete', () => Core.deleteRecoveryRecording(recording.id)); } },
    ]);
  };
  const actions: (MenuAction & { run: () => void })[] = [
    ...(!entry.audioOnly ? [{ id: 'copy', title: t('Copiar texto'), systemImage: 'doc.on.doc', disabled: !!action, run: () => { void perform('copy', () => Core.copyText(entry.text)); } }] : []),
    ...(recording ? [
      { id: 'play', title: t(playing ? 'Pausar áudio' : 'Reproduzir áudio'), systemImage: playing ? 'pause' : 'play', disabled: !!action || ['recording', 'locked'].includes(state.phase), run: () => { void perform('play', () => Core.playRecoveryRecording(recording.id)); } },
      { id: 'retry', title: t('Tentar transcrição novamente'), systemImage: 'arrow.clockwise', disabled: busy || !state.configured, run: retry },
      { id: 'undo', title: t('Desfazer edição de IA'), systemImage: 'arrow.uturn.backward', disabled: busy || !entry.rewritten || entry.text === entry.transcript, run: () => { void perform('undo', () => Core.undoRecoveryEdit(recording.id, entry.context)); } },
      { id: 'export', title: t('Extrair áudio'), systemImage: 'square.and.arrow.up', disabled: !!action, run: () => { void perform('export', () => Core.exportRecoveryRecording(recording.id)); } },
    ] : []),
    { id: 'delete', title: t('Excluir transcrição'), systemImage: 'trash', disabled: busy, destructive: true, run: remove },
  ];
  function choose(id: string) {
    const selected = actions.find(item => item.id === id);
    if (selected && !selected.disabled && entry.context === (account?.historyContext ?? '')) selected.run();
  }
  const duration = Math.max(0, Math.floor(recording?.duration ?? 0));
  const time = `${Math.floor(duration / 60)}:${String(duration % 60).padStart(2, '0')}`;
  const source = entry.sourceDevice === 'desktop' ? 'Desktop' : 'Mobile';
  const text = failed ? t('Tentar transcrever áudio de {duration}.', { duration: time }) : entry.text;
  return <ContextMenu style={{ width: '100%' }} menuID={menuID} actions={actions.map(({ run: _run, ...item }) => item)}
    onAction={event => { if (event.nativeEvent.menuID === menuID) choose(event.nativeEvent.id); }}>
    <TableRow first={first} last={last}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
        <Pressable accessibilityRole="button" accessibilityLabel={`${text}. ${historyTime(entry.createdAt, uiLanguage)}. ${source}`}
          accessibilityActions={actions.filter(item => !item.disabled).map(item => ({ name: item.id, label: item.title }))}
          onAccessibilityAction={event => choose(event.nativeEvent.actionName)}
          onPress={entry.audioOnly ? undefined : onOpen} style={{ flex: 1, minWidth: 0, flexDirection: 'row', alignItems: 'center', gap: 12 }}>
          <View style={{ alignItems: 'flex-start', gap: 4, maxWidth: 78, flexShrink: 0 }}>
            <Text style={[ui.small, { color: c.muted, fontVariant: ['tabular-nums'] }]}>{historyTime(entry.createdAt, uiLanguage)}</Text>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
              <SymbolView name={entry.sourceDevice === 'desktop' ? 'desktopcomputer' : 'iphone'} size={13} tintColor={c.muted} accessible={false} />
              <Text style={[ui.small, { color: c.muted }]}>{source}</Text>
            </View>
          </View>
          <Text numberOfLines={4} style={[ui.body, { color: failed ? c.warning : entry.audioOnly ? c.muted : c.text, flex: 1, minWidth: 0 }]}>{text}</Text>
        </Pressable>
        {failed && <Pressable accessibilityRole="button" accessibilityLabel={t('Tentar transcrição novamente')}
          disabled={busy || !state.configured} onPress={retry}
          style={{ minWidth: 44, minHeight: 44, borderRadius: 22, backgroundColor: c.warningSoft, alignItems: 'center', justifyContent: 'center', opacity: busy ? 0.4 : 1 }}>
          <SymbolView name="arrow.clockwise" size={21} tintColor={c.warning} accessible={false} />
        </Pressable>}
      </View>
    </TableRow>
  </ContextMenu>;
}
