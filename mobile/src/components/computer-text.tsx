import { useEffect, useLayoutEffect, useState, useSyncExternalStore } from 'react';
import { ActivityIndicator, Text, TextInput, View } from 'react-native';
import { router } from 'expo-router';
import Core from '../../modules/clarify-core';
import { t, uiLanguage } from '../i18n';
import { isBusy, report, useClarify } from '../state/clarify';
import { actionChoices, composerResult, ownsTextOperation, targetLanguages, TextComposerSession } from '../text-actions';
import { errorMessage } from '../errors';
import { destinationLabel } from '../processing';
import { Button, Card, ChoiceRow, NativeSheet, NavigationRow, ui, usePalette } from './ui';

export function ComputerText() {
  const c = usePalette();
  const { state, account, accountBusy, accountCommand, computerCommand, refresh } = useClarify();
  const [session] = useState(() => new TextComposerSession(Core, targetLanguages.find(item => item.value === uiLanguage)?.value ?? 'en'));
  const model = useSyncExternalStore(session.subscribe, session.getState);
  const context = account?.historyContext ?? '';
  useLayoutEffect(() => { session.setContext(context); }, [context, session]);
  useEffect(() => () => { void session.cancel(); }, [session]);
  const [sheet, setSheet] = useState<'actions' | 'language' | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [notice, setNotice] = useState('');
  const choices = actionChoices(account);
  const choice = choices.find(item => item.key === model.selected);
  const own = ownsTextOperation(model.operation, state, context);
  const result = composerResult(model, state, context);
  const busy = model.starting || model.cancelling || isBusy(state);
  const catalog = account?.mode === 'computer' ? account.computer : account;
  const catalogMessage = catalog?.textActionsStatus === 'loading' ? 'Carregando ações…'
    : catalog?.textActionsStatus === 'ready' && !choices.length ? 'Nenhuma ação salva neste destino.'
    : !['ready', 'unsupported'].includes(catalog?.textActionsStatus ?? '') ? 'Não foi possível carregar as ações. Atualize para tentar novamente.'
    : !choice && model.selected ? 'A ação mudou. Escolha uma ação da lista atual.' : '';
  async function reload() {
    setRefreshing(true); setNotice('');
    try { if (account?.mode === 'computer') await computerCommand('refresh'); else await accountCommand('refresh'); }
    catch (error) { setNotice(errorMessage(error)); }
    finally { setRefreshing(false); }
  }
  async function copy() {
    const current = session.getState();
    if (!model.operation || current.operation !== model.operation || composerResult(current, state, context) === null) return;
    try {
      const copied = await Core.copyTextOperationResult(model.operation.id, model.operation.context);
      if (copied) setNotice(t('Texto copiado.'));
      else await refresh();
    } catch (error) { setNotice(errorMessage(error)); }
  }
  return <View style={{ gap: 20 }}>
    <NavigationRow testID="actions.destination" title={t(destinationLabel(account))} icon={account?.mode === 'computer' ? 'desktopcomputer' : 'cloud'} onPress={() => router.push('/processing')} />
    <TextInput testID="actions.text" accessibilityLabel={t('Texto para processar')} multiline value={model.draft}
      onChangeText={value => session.setDraft(value)} maxLength={8000} selectionColor={c.text}
      placeholder={t('Cole ou escreva o texto')} placeholderTextColor={c.muted}
      style={[ui.input, { color: c.text, borderColor: c.controlBorder, backgroundColor: c.card, minHeight: 156, textAlignVertical: 'top' }]} />
    <Card>
      <NavigationRow testID="actions.choose" title={choice ? choice.saved ? choice.name : t(choice.name) : t('Escolher ação')} icon="wand.and.stars" onPress={() => setSheet('actions')} />
      {choice?.translation && <NavigationRow testID="actions.language" title={t('Idioma da tradução')}
        detail={targetLanguages.find(item => item.value === model.language)?.label} icon="globe" onPress={() => setSheet('language')} />}
      {choice && (!choice.enabled || !choice.ready) && <Text style={[ui.small, { color: c.muted }]}>{t(!choice.enabled ? 'Esta ação está desativada.' : 'Esta ação não está pronta neste destino.')}</Text>}
      {!!catalogMessage && <Text testID="actions.catalog-status" accessibilityLiveRegion="polite" style={[ui.small, { color: c.muted }]}>{t(catalogMessage)}</Text>}
      <Button testID="actions.refresh" loading={refreshing} disabled={accountBusy || model.starting || isBusy(state)} onPress={() => void reload()}>{t('Atualizar ações')}</Button>
    </Card>
    <Button testID="actions.run" primary disabled={busy || refreshing || accountBusy || !choice?.enabled || !choice?.ready || !model.draft.trim() || !context}
      onPress={() => { setNotice(''); if (choice) void session.start(choice).then(refresh).catch(report); }}>{t('Executar ação')}</Button>
    {(model.starting || (own && isBusy(state))) && <View style={{ gap: 12 }}>
      <ActivityIndicator accessibilityLabel={t('Processando texto…')} color={c.text} />
      <Text testID={`actions.operation.${model.operation?.id ?? 'starting'}`} accessibilityLiveRegion="polite" style={[ui.body, { color: c.muted }]}>{t('Processando texto…')}</Text>
      <Button testID="actions.cancel" loading={model.cancelling} onPress={() => void session.cancel().then(refresh).catch(report)}>{t('Cancelar')}</Button>
    </View>}
    {!!(model.error || (own && state.phase === 'error' && state.message)) && <Text testID="actions.error" accessibilityRole="alert" style={[ui.body, { color: c.danger }]}>{t(model.error || state.message!)}</Text>}
    {result !== null && <Card><Text accessibilityRole="header" style={[ui.section, { color: c.text }]}>{t('Resultado')}</Text>
      <Text testID="actions.result" selectable style={[ui.body, { color: c.text }]}>{result}</Text>
      <Button testID="actions.copy" onPress={() => void copy()}>{t('Copiar texto')}</Button>
    </Card>}
    {!!notice && <Text accessibilityLiveRegion="polite" style={[ui.small, { color: c.muted }]}>{t(notice)}</Text>}
    <NativeSheet visible={sheet !== null} title={t(sheet === 'language' ? 'Idioma da tradução' : 'Escolher ação')} onClose={() => setSheet(null)}>
      {sheet === 'language' ? targetLanguages.map(item => <ChoiceRow key={item.value} testID={`actions.target.${item.value}`} title={item.label} selected={model.language === item.value}
        onPress={() => { session.setLanguage(item.value); setSheet(null); }} />)
        : <>{!!catalogMessage && <Text style={[ui.body, { color: c.muted }]}>{t(catalogMessage)}</Text>}
          {choices.map(item => <ChoiceRow key={item.key} testID={`actions.option.${item.key}`} title={item.saved ? item.name : t(item.name)} selected={model.selected === item.key}
            detail={!item.enabled ? t('Esta ação está desativada.') : !item.ready ? t('Esta ação não está pronta neste destino.') : undefined}
            disabled={!item.enabled || !item.ready} onPress={() => { session.select(item.key); setSheet(null); }} />)}</>}
    </NativeSheet>
  </View>;
}
