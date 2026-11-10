import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { router, useFocusEffect } from 'expo-router';
import { ActivityIndicator, ScrollView, Text } from 'react-native';
import Core, { type AppleDictationSettings, type OutputPreferences } from '../../modules/clarify-core';
import { Button, ChoiceRow, Section, ui, usePalette } from '../components/ui';
import { isBusy, useClarify } from '../state/clarify';
import { errorMessage } from '../errors';
import { outputStyleLabel, outputStyles } from '../output-preferences';
import { targetLanguages } from '../text-actions';
import { t } from '../i18n';
import { DictationPolicyControls } from '../components/dictation-policy';

export default function Output() {
  const c = usePalette();
  const { account, state, accountBusy, accountCommand, computerCommand } = useClarify();
  const [preferences, setPreferences] = useState<OutputPreferences>();
  const [appleSettings, setAppleSettings] = useState<AppleDictationSettings>();
  const [appleError, setAppleError] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [supportChecked, setSupportChecked] = useState(false);
  const saving = useRef(false);
  const generation = useRef(0);
  const appleGeneration = useRef(0);
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
  const loadApple = useCallback(async () => {
    const request = ++appleGeneration.current;
    setAppleError('');
    try {
      const next = await Core.getAppleDictationSettings();
      if (request === appleGeneration.current) setAppleSettings(next);
    } catch (error) {
      if (request === appleGeneration.current) setAppleError(errorMessage(error));
    }
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
    void loadApple();
    if (account?.mode && !destination.current.supported) void refreshSupport();
    return () => { ++generation.current; ++appleGeneration.current; ++supportGeneration.current; };
  }, [load, loadApple, refreshSupport, account?.mode]));
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
  const styles = appleSettings?.enabled
    ? outputStyles.filter(item => ['default', 'formal', 'casual'].includes(item.value)) : outputStyles;
  const legacy = preferences && !styles.some(item => item.value === preferences.style);
  return <ScrollView testID="app.output" style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={ui.content} contentInsetAdjustmentBehavior="automatic">
    <Text style={[ui.small, { color: c.muted }]}>{t('As alterações valem para a próxima operação.')}</Text>
    {!!appleError && <>
      <Text testID="output.apple-error" accessibilityRole="alert" style={[ui.body, { color: c.danger }]}>{t(appleError)}</Text>
      <Button testID="output.apple-retry" onPress={() => void loadApple()}>{t('Tentar carregar novamente')}</Button>
    </>}
    {!supported && supportChecked && !error && <Text accessibilityRole="alert" style={[ui.body, { color: c.muted }]}>{t('Atualize o Clarify neste destino para mudar a saída do ditado.')}</Text>}
    {!!error && <Text testID="output.error" accessibilityRole="alert" style={[ui.body, { color: c.danger }]}>{t(error)}</Text>}
    {(!supported || !!error) && <Button testID="output.refresh" loading={refreshing}
      disabled={pending || busy || !account?.mode}
      onPress={() => { void load(); void refreshSupport(); }}>{t('Tentar carregar novamente')}</Button>}
    {!preferences && !error && <ActivityIndicator />}
    {preferences && <>
      <Section title={t('Idioma de saída')}>
        {[{ value: 'auto', label: `🌐 ${t('Idioma original')}` }, ...targetLanguages].map(item => <ChoiceRow key={item.value}
          testID={`output.language.${item.value}`} title={item.label} selected={preferences.language === item.value} disabled={pending || refreshing || (!supported && item.value !== 'auto')}
          onPress={() => void save('language', item.value)} />)}
      </Section>
      <Section title={t('Estilo')}>
        {appleSettings?.enabled && <Text style={[ui.small, { color: c.muted }]}>{t('A reescrita com Apple aceita apenas os estilos Padrão, Formal ou Casual.')}</Text>}
        {styles.map(item => <ChoiceRow key={item.value} testID={`output.style.${item.value}`} title={t(item.label)}
          selected={preferences.style === item.value} disabled={pending || refreshing || (!supported && item.value !== 'default')} onPress={() => void save('style', item.value)} />)}
        {legacy && <ChoiceRow testID="output.style.unsupported" title={t(outputStyleLabel(preferences.style))}
          detail={appleSettings?.enabled ? t('O estilo salvo não é compatível com a reescrita com Apple. Selecione Padrão, Formal ou Casual.') : undefined}
          selected disabled onPress={() => {}} />}
      </Section>
    </>}
    {pending && <ActivityIndicator accessibilityLabel={t('Salvando…')} />}
    <DictationPolicyControls outputLanguage={preferences?.language} />
    <Button testID="output.close" onPress={() => router.back()}>{t('Fechar')}</Button>
  </ScrollView>;
}
