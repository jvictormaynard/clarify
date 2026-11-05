import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { useFocusEffect } from 'expo-router';
import { AppState, Text, View } from 'react-native';
import Core, { type AppleRewriteAvailability, type OutputStyle } from '../../modules/clarify-core';
import { AppleRewriteSession } from '../apple-rewrite';
import { DraftTextInput } from '../components/draft-text-input';
import { Button, Card, ChoiceRow, KeyboardPage, NativeSheet, NavigationRow, ScreenHeader, ui, usePalette } from '../components/ui';
import { errorMessage } from '../errors';
import { t } from '../i18n';
import { outputStyleLabel } from '../output-preferences';
import { targetLanguages } from '../text-actions';

const styles: OutputStyle[] = ['default', 'formal', 'casual', 'very_casual', 'natural', 'informal', 'organized'];

export default function AppleRewrite() {
  const c = usePalette();
  const [session] = useState(() => new AppleRewriteSession(Core));
  const model = useSyncExternalStore(session.subscribe, session.getState);
  const [availability, setAvailability] = useState<AppleRewriteAvailability>();
  const [loadError, setLoadError] = useState('');
  const [preferencesLoaded, setPreferencesLoaded] = useState(false);
  const availabilityGeneration = useRef(0);
  const [sheet, setSheet] = useState<'language' | 'style' | null>(null);
  const refreshAvailability = useCallback(async () => {
    const request = ++availabilityGeneration.current;
    setAvailability(undefined); setLoadError('');
    try {
      const status = await Core.getAppleRewriteAvailability();
      if (request === availabilityGeneration.current) setAvailability(status);
    } catch (error) { if (request === availabilityGeneration.current) setLoadError(errorMessage(error)); }
  }, []);
  useEffect(() => {
    let active = true;
    void Core.getOutputPreferences().then(preferences => {
      if (active) { session.setPreferences(preferences); setPreferencesLoaded(true); }
    }).catch(error => { if (active) setLoadError(errorMessage(error)); });
    return () => { active = false; };
  }, [session]);
  useFocusEffect(useCallback(() => {
    void refreshAvailability();
    const subscription = AppState.addEventListener('change', state => {
      if (state === 'active') void refreshAvailability();
      else void session.cancel();
    });
    return () => { ++availabilityGeneration.current; subscription.remove(); void session.cancel(); };
  }, [refreshAvailability, session]));
  const language = model.preferences.language;
  const languageLabel = targetLanguages.find(item => item.value === language)?.label ?? t('Manter idioma original');
  return <KeyboardPage>
    <ScreenHeader title={t('Teste do Apple Intelligence')} subtitle={t('Cole uma transcrição curta para testar a reescrita neste iPhone.')} />
    <Card>
      <Text style={[ui.body, { color: c.text }]}>{t('Este teste usa somente o modelo da Apple no dispositivo. O texto não é salvo no histórico. Revise o resultado antes de usar.')}</Text>
      <Text testID="apple.status" accessibilityLiveRegion="polite" style={[ui.small, { color: c.muted }]}>
        {availability?.message ?? (loadError || t('Verificando disponibilidade…'))}
      </Text>
      {availability && <Text style={[ui.small, { color: c.muted }]}>{t('Limite do teste: {v0} bytes de texto.', { v0: availability.maxInputBytes })}</Text>}
      <Button testID="apple.refresh" disabled={model.busy} onPress={() => void refreshAvailability()}>{t('Atualizar disponibilidade')}</Button>
    </Card>
    <DraftTextInput testID="apple.source" accessibilityLabel={t('Texto para processar')} initialValue="" multiline
      onChangeText={source => session.setSource(source)} selectionColor={c.text}
      placeholder={t('Cole ou escreva o texto')} placeholderTextColor={c.muted}
      style={[ui.input, { color: c.text, borderColor: c.controlBorder, backgroundColor: c.card, minHeight: 156, textAlignVertical: 'top' }]} />
    {preferencesLoaded && <Card>
      <NavigationRow testID="apple.language" title={t('Idioma de saída')} detail={languageLabel} icon="globe" onPress={() => setSheet('language')} />
      <NavigationRow testID="apple.style" title={t('Estilo de escrita')} detail={t(outputStyleLabel(model.preferences.style))} icon="textformat" onPress={() => setSheet('style')} />
    </Card>}
    <Button testID="apple.rewrite" primary disabled={!preferencesLoaded || !availability?.available || !model.source.trim()} loading={model.busy} onPress={() => void session.run()}>{t('Reescrever com Apple Intelligence')}</Button>
    {model.busy && <Button testID="apple.cancel" onPress={() => void session.cancel()}>{t('Cancelar')}</Button>}
    {!!model.error && <Text testID="apple.error" accessibilityRole="alert" style={[ui.body, { color: c.danger }]}>{t(model.error)}</Text>}
    {!!model.result && <View testID="apple.result" style={{ gap: 12 }}>
      <Text accessibilityRole="header" style={[ui.section, { color: c.text }]}>{t('Resultado')}</Text>
      <Text selectable style={[ui.body, { color: c.text }]}>{model.result}</Text>
      <Text style={[ui.small, { color: c.muted }]}>{t('Tempo: {v0} ms.', { v0: model.elapsedMS ?? 0 })}</Text>
    </View>}
    <NativeSheet visible={sheet !== null} title={t(sheet === 'style' ? 'Estilo de escrita' : 'Idioma de saída')} onClose={() => setSheet(null)}>
      {sheet === 'style' ? styles.map(style => <ChoiceRow key={style} testID={`apple.style.${style}`} title={t(outputStyleLabel(style))} selected={model.preferences.style === style}
        onPress={() => { session.setPreferences({ ...model.preferences, style }); setSheet(null); }} />)
        : [{ value: 'auto' as const, label: t('Manter idioma original') }, ...targetLanguages].map(item => <ChoiceRow key={item.value} testID={`apple.language.${item.value}`} title={item.label} selected={language === item.value}
          onPress={() => { session.setPreferences({ ...model.preferences, language: item.value }); setSheet(null); }} />)}
    </NativeSheet>
  </KeyboardPage>;
}
