import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { Stack, useFocusEffect } from 'expo-router';
import { AppState, Keyboard, Pressable, Text, View } from 'react-native';
import { SymbolView } from 'expo-symbols';
import Core, { type AppleRewriteAvailability } from '../../modules/clarify-core';
import { AppleRewriteSession, appleRewriteStyles } from '../apple-rewrite';
import { DraftTextInput } from '../components/draft-text-input';
import { Button, Card, ChoiceRow, KeyboardPage, NativeSheet, NavigationRow, ScreenHeader, ui, usePalette } from '../components/ui';
import { errorMessage } from '../errors';
import { t } from '../i18n';
import { outputStyleLabel } from '../output-preferences';
import { targetLanguages } from '../text-actions';

export default function AppleRewrite() {
  const c = usePalette();
  const [session] = useState(() => new AppleRewriteSession(Core));
  const model = useSyncExternalStore(session.subscribe, session.getState);
  const [availability, setAvailability] = useState<AppleRewriteAvailability>();
  const [loadError, setLoadError] = useState('');
  const [nativeOpening, setNativeOpening] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const [privateProbe, setPrivateProbe] = useState('');
  const [probing, setProbing] = useState(false);
  const probeGeneration = useRef(0);
  useEffect(() => () => { ++probeGeneration.current; }, []);
  useEffect(() => setShowDetails(false), [model.report]);
  const [preferencesLoaded, setPreferencesLoaded] = useState(false);
  const [keyboardVisible, setKeyboardVisible] = useState(() => Keyboard.isVisible());
  const availabilityGeneration = useRef(0);
  const [sheet, setSheet] = useState<'language' | 'style' | null>(null);
  useEffect(() => {
    const shown = Keyboard.addListener('keyboardDidShow', () => setKeyboardVisible(true));
    const hidden = Keyboard.addListener('keyboardDidHide', () => setKeyboardVisible(false));
    return () => { shown.remove(); hidden.remove(); };
  }, []);
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
  const inspectPrivate = async () => {
    if (probing) return;
    const generation = ++probeGeneration.current;
    setProbing(true); setPrivateProbe(''); setLoadError('');
    try {
      const report = await Core.getPrivateAppleRewriteProbe();
      if (generation === probeGeneration.current) setPrivateProbe(JSON.stringify(report, null, 2).slice(0, 16000));
    } catch (error) { if (generation === probeGeneration.current) setLoadError(errorMessage(error)); }
    finally { if (generation === probeGeneration.current) setProbing(false); }
  };
  const openNative = async (privateController = false) => {
    if (nativeOpening) return;
    setNativeOpening(true); setLoadError('');
    try {
      await session.cancel();
      Keyboard.dismiss();
      if (privateController) await Core.openPrivateAppleWritingTools(model.source, language, model.preferences.style);
      else await Core.openAppleWritingTools(model.source, language);
    } catch (error) { setLoadError(errorMessage(error)); }
    finally { setNativeOpening(false); }
  };
  return <>
    <Stack.Screen options={{ headerRight: () => keyboardVisible ? <Pressable testID="apple.dismiss-keyboard"
      accessibilityRole="button" accessibilityLabel={t('Concluir')} onPress={Keyboard.dismiss}
      style={{ minWidth: 44, minHeight: 44, alignItems: 'center', justifyContent: 'center' }}>
      <SymbolView name="keyboard.chevron.compact.down" size={22} tintColor={c.text} accessible={false} />
    </Pressable> : null }} />
    <KeyboardPage>
    <ScreenHeader title={t('Teste do Apple Intelligence')} subtitle={t('Cole uma transcrição curta para testar a reescrita neste iPhone.')} />
    <Card>
      <Text style={[ui.body, { color: c.text }]}>{t('O botão Reescrever usa o modelo local e a tradução local da Apple. O texto não é salvo no histórico. Revise o resultado antes de usar.')}</Text>
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
    <Card>
      <Text style={[ui.section, { color: c.text }]}>{t('Geração')}</Text>
      <ChoiceRow title={t('Repetível')} selected={model.deterministic} onPress={() => session.setDeterministic(true)} />
      <ChoiceRow title={t('Padrão do modelo')} selected={!model.deterministic} onPress={() => session.setDeterministic(false)} />
    </Card>
    <Button testID="apple.rewrite" primary disabled={!preferencesLoaded || !availability?.available || !model.source.trim()} loading={model.busy} onPress={() => void session.run()}>{t('Reescrever com Apple Intelligence')}</Button>
    {model.busy && <Button testID="apple.cancel" onPress={() => void session.cancel()}>{t('Cancelar')}</Button>}
    {!!model.error && <Text testID="apple.error" accessibilityRole="alert" style={[ui.body, { color: c.danger }]}>{t(model.error)}</Text>}
    {!!loadError && <Text accessibilityRole="alert" style={[ui.body, { color: c.danger }]}>{loadError}</Text>}
    <Button disabled={model.busy || !model.source.trim()} loading={nativeOpening} onPress={() => void openNative()}>{t('Comparar com as Ferramentas de Escrita')}</Button>
    <Text style={[ui.small, { color: c.muted }]}>{t('A comparação abre os controles da Apple e permite preparar os idiomas para tradução local. Ela pode usar o Private Cloud Compute.')}</Text>
    <Card>
      <Text style={[ui.section, { color: c.text }]}>{t('Experimento com APIs privadas da Apple')}</Text>
      <Text style={[ui.small, { color: c.muted }]}>{t('Estas rotas podem usar modelos locais ou na nuvem da Apple. Elas podem estar indisponíveis neste iOS. O original é preservado em caso de falha.')}</Text>
      <Button disabled={model.busy || nativeOpening} loading={probing} onPress={() => void inspectPrivate()}>{t('Inspecionar interfaces privadas')}</Button>
      {!!privateProbe && <Text selectable style={[ui.small, { color: c.muted }]}>{privateProbe}</Text>}
      <Text style={[ui.small, { color: c.muted }]}>{t('A rota direta é uma inspeção de interface nesta build. Ela ainda não inicia uma reescrita.')}</Text>
      <Button testID="apple.private.rewrite" disabled={!preferencesLoaded || model.busy || nativeOpening || !model.source.trim()} onPress={() => void session.run('private')}>{t('Verificar rota privada TextComposer')}</Button>
      <Button testID="apple.private.controller" disabled={!preferencesLoaded || model.busy || nativeOpening || !model.source.trim()} onPress={() => void openNative(true)}>{t('Testar controlador privado das Ferramentas de Escrita')}</Button>
    </Card>
    {!!model.report && <Card>
      <Button onPress={() => setShowDetails(value => !value)}>{t(showDetails ? 'Ocultar detalhes do teste' : 'Mostrar detalhes do teste')}</Button>
      {showDetails && <>
        <Text selectable style={[ui.small, { color: c.muted }]}>{model.report.stage} · {model.report.code || 'OK'} · {model.elapsedMS} ms</Text>
        {!!model.report.route && <Text selectable style={[ui.small, { color: c.muted }]}>{model.report.route}</Text>}
        {!!model.report.diagnostics && <Text selectable style={[ui.small, { color: c.muted }]}>{model.report.diagnostics}</Text>}
        {!!model.report.rewritten && <Text selectable style={[ui.body, { color: c.text }]}>{model.report.rewritten}</Text>}
        {!!model.report.candidate && !!model.report.error && <>
          <Text style={[ui.section, { color: c.danger }]}>{t('Resposta rejeitada. Não use como resultado final.')}</Text>
          <Text selectable style={[ui.body, { color: c.text }]}>{model.report.candidate}</Text>
        </>}
      </>}
    </Card>}
    {!!model.result && <View testID="apple.result" style={{ gap: 12 }}>
      <Text accessibilityRole="header" style={[ui.section, { color: c.text }]}>{t('Resultado')}</Text>
      <Text selectable style={[ui.body, { color: c.text }]}>{model.result}</Text>
      <Text style={[ui.small, { color: c.muted }]}>{t('Tempo: {v0} ms.', { v0: model.elapsedMS ?? 0 })}</Text>
    </View>}
    <NativeSheet visible={sheet !== null} title={t(sheet === 'style' ? 'Estilo de escrita' : 'Idioma de saída')} onClose={() => setSheet(null)}>
      {sheet === 'style' ? appleRewriteStyles.map(style => <ChoiceRow key={style} testID={`apple.style.${style}`} title={t(outputStyleLabel(style))} selected={model.preferences.style === style}
        onPress={() => { session.setPreferences({ ...model.preferences, style }); setSheet(null); }} />)
        : [{ value: 'auto' as const, label: t('Manter idioma original') }, ...targetLanguages].map(item => <ChoiceRow key={item.value} testID={`apple.language.${item.value}`} title={item.label} selected={language === item.value}
          onPress={() => { session.setPreferences({ ...model.preferences, language: item.value }); setSheet(null); }} />)}
    </NativeSheet>
    </KeyboardPage>
  </>;
}
