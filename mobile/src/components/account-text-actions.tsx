import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useIsFocused } from 'expo-router';
import { Alert, Switch, Text, View } from 'react-native';
import Core, { type AccountTextActionDefinition, type AccountTextActionLibrary } from '../../modules/clarify-core';
import { actionReplacement, ownsActionLibrary } from '../account-text-actions';
import { t } from '../i18n';
import { isBusy, report, useClarify } from '../state/clarify';
import { DraftTextInput } from './draft-text-input';
import { Button, Card, ChoiceRow, NativeSheet, ui, usePalette } from './ui';

type Editor = { value: AccountTextActionDefinition; originalID: string | null; base: AccountTextActionLibrary; rebased?: boolean };
export function AccountTextActions() {
  const c = usePalette();
  const { account, state, accountBusy, refresh, refreshAccount } = useClarify();
  const focused = useIsFocused();
  const context = account?.historyContext ?? '';
  const computer = account?.mode === 'computer';
  const signedIn = !!account?.signedIn;
  const [library, setLibrary] = useState<AccountTextActionLibrary | null>(null);
  const [editing, setEditing] = useState<Editor | null>(null);
  const [working, setWorking] = useState(false);
  const [failed, setFailed] = useState(false);
  const request = useRef(0);
  const current = useRef({ context, computer, signedIn });
  useLayoutEffect(() => { current.current = { context, computer, signedIn }; }, [context, computer, signedIn]);
  const busy = working || accountBusy || !!account?.busy || isBusy(state);
  const owned = (base: AccountTextActionLibrary) => ownsActionLibrary(base, current.current.context, current.current.computer, current.current.signedIn);
  useEffect(() => {
    if (!focused || computer || !signedIn) return;
    const sequence = ++request.current;
    void Core.getAccountTextActions(context).then(async value => {
      if (request.current === sequence && owned(value)) {
        setLibrary(value); setFailed(false);
        await refreshAccount();
      }
    }).catch(() => { if (request.current === sequence) setFailed(true); });
    // This ref is a request counter, not a React node. Cleanup rejects late results.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    return () => { ++request.current; };
  }, [context, computer, signedIn, focused, refreshAccount]);

  function edit(value?: AccountTextActionDefinition, duplicate = false) {
    if (!library || !owned(library)) return;
    setEditing({ base: library, originalID: value && !duplicate ? value.id : null,
      value: value ? { ...value, id: duplicate ? Core.newOperationID() : value.id } : { id: Core.newOperationID(), name: '', prompt: '', kind: 'custom', enabled: true } });
  }
  async function save(remove = false) {
    if (!editing || !owned(editing.base) || busy) return;
    const sequence = ++request.current;
    setWorking(true);
    try {
      const rows = actionReplacement(editing.base, editing.value, editing.originalID, remove);
      const value = await Core.saveAccountTextActions(rows, editing.base.revision, editing.base.lease, editing.base.context);
      if (sequence === request.current && owned(value)) { setLibrary(value); setEditing(null); setFailed(false); }
      await refresh();
    } catch (error) { if (sequence === request.current) { setFailed(true); report(error); } }
    finally { setWorking(false); }
  }
  async function reload(keepDraft = false) {
    if (busy || (keepDraft && (!editing || !owned(editing.base)))) return;
    const sequence = ++request.current;
    setWorking(true);
    try {
      const value = await Core.getAccountTextActions(context);
      if (sequence !== request.current || !owned(value)) return;
      setLibrary(value); setFailed(false);
      if (keepDraft) setEditing(old => old && owned(old.base) ? { ...old, base: value, rebased: true } : old);
      await refreshAccount();
    } catch (error) { if (sequence === request.current) { setFailed(true); report(error); } }
    finally { setWorking(false); }
  }
  const ready = library && ownsActionLibrary(library, context, computer, signedIn);
  const editorOwned = editing && ownsActionLibrary(editing.base, context, computer, signedIn);
  const latest = editing?.base.actions.find(row => row.id === editing.originalID);
  const canSave = editing && (!editing.originalID || latest) && editorOwned && !!editing.value.name.trim() && !!editing.value.prompt.trim();
  return <>
    <Card>
      <Text accessibilityRole="header" style={[ui.section, { color: c.text }]}>{t('Gerenciar ações')}</Text>
      {computer ? <Text style={[ui.body, { color: c.muted }]}>{t('Gerencie estas ações no computador pareado.')}</Text>
        : !signedIn ? <Text style={[ui.body, { color: c.muted }]}>{t('Entre na sua conta primeiro.')}</Text> : <>
          {failed && <Text accessibilityRole="alert" style={[ui.body, { color: c.text }]}>{t('Não foi possível salvar ou carregar as ações. Seu rascunho foi mantido.')}</Text>}
          <Button disabled={busy} onPress={() => void reload()}>{t('Atualizar lista')}</Button>
          <Button disabled={busy || !ready || library.actions.length >= 64} onPress={() => edit()}>{t('Adicionar ação')}</Button>
          {ready && library.actions.map(row => <View key={row.id} style={{ gap: 8 }}>
            <Button disabled={busy} onPress={() => edit(row)}>{row.name}</Button>
            <Text style={[ui.small, { color: c.muted }]}>{row.enabled ? t('Ativa') : t('Desativada')}</Text>
            <Button disabled={busy || library.actions.length >= 64} onPress={() => edit(row, true)}>{t('Duplicar ação')}</Button>
          </View>)}
        </>}
    </Card>
    <NativeSheet visible={editing !== null} title={t('Editar ação')} onClose={() => { if (!working) setEditing(null); }}>
      {editing && <>
        {editing.rebased && latest && <Card>
          <Text style={[ui.small, { color: c.muted }]}>{t('Current server version')}</Text>
          <Text style={[ui.body, { color: c.text }]}>{latest.name}</Text>
          <Text style={[ui.body, { color: c.text }]}>{latest.prompt}</Text>
          <Text style={[ui.small, { color: c.muted }]}>{latest.enabled ? t('Ativa') : t('Desativada')}</Text>
        </Card>}
        <Text style={[ui.small, { color: c.muted }]}>{t('Nome da ação')}</Text>
        <DraftTextInput initialValue={editing.value.name} accessibilityLabel={t('Nome da ação')} maxLength={80} editable={!working}
          onChangeText={name => setEditing(old => old ? { ...old, value: { ...old.value, name } } : old)} style={[ui.input, { color: c.text, borderColor: c.controlBorder }]} />
        <Text style={[ui.small, { color: c.muted }]}>{t('Instruções da ação')}</Text>
        <DraftTextInput initialValue={editing.value.prompt} accessibilityLabel={t('Instruções da ação')} multiline editable={!working} textAlignVertical="top"
          onChangeText={prompt => setEditing(old => old ? { ...old, value: { ...old.value, prompt } } : old)} style={[ui.input, { color: c.text, borderColor: c.controlBorder, minHeight: 160 }]} />
        {(['rewrite', 'translation', 'custom'] as const).map(kind => <ChoiceRow key={kind} title={t(kind === 'rewrite' ? 'Reescrita' : kind === 'translation' ? 'Tradução' : 'Personalizada')} selected={editing.value.kind === kind} disabled={working}
          onPress={() => setEditing(old => old ? { ...old, value: { ...old.value, kind } } : old)} />)}
        <View style={ui.row}><Text style={[ui.body, { color: c.text }]}>{t('Ativa')}</Text><Switch accessibilityLabel={t('Ativa')} disabled={working} value={editing.value.enabled}
          onValueChange={enabled => setEditing(old => old ? { ...old, value: { ...old.value, enabled } } : old)} /></View>
        {!editorOwned && <Text accessibilityRole="alert" style={[ui.body, { color: c.text }]}>{t('A conta ou o destino mudou. Seu rascunho foi mantido.')}</Text>}
        {failed && <Button disabled={busy || !editorOwned} onPress={() => Alert.alert(t('Recarregar a lista?'), t('O rascunho será mantido. Revise as ações atuais antes de salvar.'),
          [{ text: t('Cancelar'), style: 'cancel' }, { text: t('Continuar'), onPress: () => void reload(true) }])}>{t('Recarregar e manter rascunho')}</Button>}
        <Button disabled={busy || !canSave} loading={working} onPress={() => void save()}>{t('Salvar')}</Button>
        {editing.originalID && <Button disabled={busy || !editorOwned} destructive onPress={() => Alert.alert(t('Excluir ação?'), editing.value.name,
          [{ text: t('Cancelar'), style: 'cancel' }, { text: t('Excluir'), style: 'destructive', onPress: () => void save(true) }])}>{t('Excluir')}</Button>}
      </>}
    </NativeSheet>
  </>;
}
