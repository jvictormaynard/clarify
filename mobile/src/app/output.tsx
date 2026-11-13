import { useCallback, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { router, useFocusEffect } from 'expo-router';
import { ActivityIndicator, ScrollView, Text } from 'react-native';
import Core, { type OutputPreferences } from '../../modules/clarify-core';
import { Button, ChoiceRow, Section, ui, usePalette } from '../components/ui';
import { isBusy, useClarify } from '../state/clarify';
import { errorMessage } from '../errors';
import { outputStyleLabel, outputStyles } from '../output-preferences';
import { targetLanguages } from '../text-actions';
import { t } from '../i18n';
import { DictationPolicyControls } from '../components/dictation-policy';

export default function Output({ close = true, introduction }: { close?: boolean; introduction?: ReactNode } = {}) {
  const c = usePalette();
  const { account, state, accountBusy, accountCommand, computerCommand } = useClarify();
  const [preferences, setPreferences] = useState<OutputPreferences>();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [supportChecked, setSupportChecked] = useState(false);
  const saving = useRef(false);
  const generation = useRef(0);
  const supportGeneration = useRef(0);
  const refreshInFlight = useRef(false);
  const supported = account?.outputPreferencesSupported === true;
  const busy = accountBusy || isBusy(state);
  const destination = useRef({ mode: account?.mode, busy, supported });
  useLayoutEffect(() => {
    destination.current = { mode: account?.mode, busy, supported };
  }, [account?.mode, busy, supported]);
  const load = useCallback(async () => {
    const request = ++generation.current;
    setError('');
    try { const next = await Core.getOutputPreferences(); if (request === generation.current) setPreferences(next); }
    catch (error) { if (request === generation.current) setError(errorMessage(error)); }
  }, []);
  const refreshSupport = useCallback(async () => {
    const { mode, busy } = destination.current;
    if (!mode || busy || refreshInFlight.current) return;
    const request = ++supportGeneration.current;
    refreshInFlight.current = true; setRefreshing(true); setSupportChecked(false); setError('');
    try {
      if (mode === 'computer') await computerCommand('refresh');
      else await accountCommand('refresh');
      if (request === supportGeneration.current) setSupportChecked(true);
    } catch (error) {
      if (request === supportGeneration.current) setError(errorMessage(error));
    } finally { refreshInFlight.current = false; setRefreshing(false); }
  }, [accountCommand, computerCommand]);
  useFocusEffect(useCallback(() => {
    void load();
    if (account?.mode && !destination.current.supported) void refreshSupport();
    return () => { ++generation.current; ++supportGeneration.current; };
  }, [load, refreshSupport, account?.mode]));
  async function save(key: 'language' | 'style', value: string) {
    const clearsOverride = key === 'language' ? value === 'auto' : value === 'default';
    if ((!supported && !clearsOverride) || saving.current || refreshInFlight.current) return;
    saving.current = true; setPending(true); setError('');
    const request = ++generation.current;
    try {
      const next = await Core.setOutputPreference(key, value);
      if (request === generation.current) setPreferences(next);
    } catch (error) { if (request === generation.current) setError(errorMessage(error)); }
    finally { saving.current = false; setPending(false); }
  }
  const legacy = preferences && !outputStyles.some(item => item.value === preferences.style);
  return <ScrollView testID="app.output" style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={ui.content} contentInsetAdjustmentBehavior="automatic">
    {introduction}
    {!supported && supportChecked && !error && <Text accessibilityRole="alert" style={[ui.body, { color: c.muted }]}>{t('Atualize o Clarify neste destino para mudar a saída do ditado.')}</Text>}
    {!!error && <Text testID="output.error" accessibilityRole="alert" style={[ui.body, { color: c.danger }]}>{t(error)}</Text>}
    {(!supported || !!error) && <Button testID="output.refresh" loading={refreshing}
      disabled={pending || busy || !account?.mode}
      onPress={() => { void load(); void refreshSupport(); }}>{t('Tentar carregar novamente')}</Button>}
    {!preferences && !error && <ActivityIndicator />}
    <DictationPolicyControls outputLanguage={preferences?.language} more={preferences && <><Section title={t('Idioma de saída')}>
        {[{ value: 'auto', label: `🌐 ${t('Idioma original')}` }, ...targetLanguages].map(item => <ChoiceRow key={item.value}
          testID={`output.language.${item.value}`} title={item.label} selected={preferences.language === item.value} disabled={pending || refreshing || (!supported && item.value !== 'auto')}
          onPress={() => void save('language', item.value)} />)}
      </Section>
        {!supported && <ChoiceRow testID="output.style.default" title={t('Padrão')} selected={preferences.style === 'default'}
          disabled={pending || refreshing} onPress={() => void save('style', 'default')} />}
      </>} tone={preferences && <Section title={t('Tom')}>
        {outputStyles.map(item => <ChoiceRow key={item.value} testID={`output.style.${item.value}`} title={t(item.label)}
          selected={preferences.style === item.value} disabled={pending || refreshing || !supported} onPress={() => void save('style', item.value)} />)}
        {legacy && <ChoiceRow title={t(outputStyleLabel(preferences.style))} selected disabled onPress={() => {}} />}
      </Section>} />
    {pending && <ActivityIndicator accessibilityLabel={t('Salvando…')} />}
    {close && <Button testID="output.close" onPress={() => router.back()}>{t('Fechar')}</Button>}
  </ScrollView>;
}
