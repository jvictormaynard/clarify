import { useCallback, useRef, useState } from 'react';
import { router, useFocusEffect } from 'expo-router';
import { ActivityIndicator, ScrollView, Text } from 'react-native';
import Core, { type OutputPreferences } from '../../modules/clarify-core';
import { Button, ChoiceRow, Section, ui, usePalette } from '../components/ui';
import { useClarify } from '../state/clarify';
import { errorMessage } from '../errors';
import { outputStyleLabel, outputStyles, visibleOutputStyle } from '../output-preferences';
import { targetLanguages } from '../text-actions';
import { t } from '../i18n';

export default function Output() {
  const c = usePalette();
  const { account } = useClarify();
  const [preferences, setPreferences] = useState<OutputPreferences>();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const saving = useRef(false);
  const generation = useRef(0);
  const supported = account?.outputPreferencesSupported === true;
  const load = useCallback(async () => {
    const request = ++generation.current;
    setError('');
    try { const next = await Core.getOutputPreferences(); if (request === generation.current) setPreferences(next); }
    catch (error) { if (request === generation.current) setError(errorMessage(error)); }
  }, []);
  useFocusEffect(useCallback(() => { void load(); return () => { ++generation.current; }; }, [load]));
  async function save(key: 'language' | 'style', value: string) {
    const clearsOverride = key === 'language' ? value === 'auto' : value === 'default';
    if ((!supported && !clearsOverride) || saving.current) return;
    saving.current = true; setPending(true); setError('');
    const request = ++generation.current;
    try {
      const next = await Core.setOutputPreference(key, value);
      if (request === generation.current) setPreferences(next);
    } catch (error) { if (request === generation.current) setError(errorMessage(error)); }
    finally { saving.current = false; setPending(false); }
  }
  const legacy = preferences && !['default', ...outputStyles.map(item => item.value)].includes(preferences.style);
  return <ScrollView testID="app.output" style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={ui.content} contentInsetAdjustmentBehavior="automatic">
    <Text style={[ui.small, { color: c.muted }]}>{t('As alterações valem para a próxima operação.')}</Text>
    {!supported && <Text accessibilityRole="alert" style={[ui.body, { color: c.muted }]}>{t('Atualize o Clarify neste destino para mudar a saída do ditado.')}</Text>}
    {!!error && <><Text testID="output.error" accessibilityRole="alert" style={[ui.body, { color: c.danger }]}>{t(error)}</Text>
      {!preferences && <Button onPress={() => void load()}>{t('Tentar carregar novamente')}</Button>}</>}
    {!preferences && !error && <ActivityIndicator />}
    {preferences && <>
      <Section title={t('Idioma de saída')}>
        {[{ value: 'auto', label: `🌐 ${t('Idioma original')}` }, ...targetLanguages].map(item => <ChoiceRow key={item.value}
          testID={`output.language.${item.value}`} title={item.label} selected={preferences.language === item.value} disabled={pending || (!supported && item.value !== 'auto')}
          onPress={() => void save('language', item.value)} />)}
      </Section>
      <Section title={t('Estilo')}>
        {outputStyles.map(item => <ChoiceRow key={item.value} testID={`output.style.${item.value}`} title={t(item.label)}
          selected={visibleOutputStyle(preferences.style) === item.value} disabled={pending || (!supported && item.value !== 'default')} onPress={() => void save('style', item.value)} />)}
        {legacy && <ChoiceRow title={t(outputStyleLabel(preferences.style))} selected disabled onPress={() => {}} />}
      </Section>
    </>}
    {pending && <ActivityIndicator accessibilityLabel={t('Salvando…')} />}
    <Button testID="output.close" onPress={() => router.back()}>{t('Fechar')}</Button>
  </ScrollView>;
}
