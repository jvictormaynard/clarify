import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { router, useFocusEffect } from 'expo-router';
import { ActivityIndicator, AppState, ScrollView, Switch, Text, View } from 'react-native';
import Core, { type AppleDictationSettings } from '../../modules/clarify-core';
import { Button, Card, NavigationRow, Section, ui, usePalette } from '../components/ui';
import { errorMessage } from '../errors';
import { t } from '../i18n';
import { isBusy, useClarify } from '../state/clarify';

export default function AppleDictation() {
  const c = usePalette();
  const { account, accountBusy, state } = useClarify();
  const [settings, setSettings] = useState<AppleDictationSettings>();
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const generation = useRef(0);
  const focused = useRef(false);
  const saving = useRef<Promise<AppleDictationSettings> | null>(null);
  const context = `${account?.mode ?? ''}:${account?.historyContext ?? ''}`;
  const currentContext = useRef(context);
  const busy = accountBusy || isBusy(state);
  const busyRef = useRef(busy);
  useLayoutEffect(() => { busyRef.current = busy; currentContext.current = context; }, [busy, context]);
  const load = useCallback(async () => {
    const request = ++generation.current;
    setLoading(true); setError('');
    try {
      // A save can finish after this screen loses focus. Read its persisted result.
      if (saving.current) await saving.current.catch(() => {});
      if (!focused.current || request !== generation.current || context !== currentContext.current) return;
      const next = await Core.getAppleDictationSettings();
      if (request === generation.current && context === currentContext.current) setSettings(next);
    } catch (error) {
      if (request === generation.current && context === currentContext.current) setError(errorMessage(error));
    } finally {
      if (request === generation.current && context === currentContext.current) { setLoading(false); setPending(false); }
    }
  }, [context]);
  useFocusEffect(useCallback(() => {
    focused.current = true;
    setSettings(undefined);
    void load();
    const subscription = AppState.addEventListener('change', next => {
      if (next === 'active') void load();
      else { ++generation.current; setLoading(true); }
    });
    return () => { focused.current = false; ++generation.current; subscription.remove(); };
  }, [load]));
  async function changeEnabled(enabled: boolean) {
    if (!focused.current || saving.current || loading || busyRef.current || !settings || (enabled && !settings.available)) return;
    const request = ++generation.current;
    setPending(true); setError('');
    try {
      const operation = Core.setAppleDictationEnabled(enabled);
      saving.current = operation;
      const next = await operation;
      if (request === generation.current && context === currentContext.current) setSettings(next);
    } catch (error) {
      if (request === generation.current && context === currentContext.current) setError(errorMessage(error));
    } finally {
      saving.current = null;
      if (request === generation.current && context === currentContext.current) setPending(false);
    }
  }
  return <ScrollView testID="app.apple-dictation" style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={ui.content} contentInsetAdjustmentBehavior="automatic">
    <Card>
      <View style={ui.row}>
        <Text style={[ui.body, { color: c.text, flex: 1 }]}>{t('Reescrita com Apple')}</Text>
        <Switch testID="apple-dictation.enabled" accessibilityLabel={t('Reescrita com Apple')}
          value={settings?.enabled ?? false} disabled={!settings || loading || pending || busy || (!settings.available && !settings.enabled)}
          onValueChange={value => void changeEnabled(value)} />
      </View>
      <Text style={[ui.small, { color: c.muted }]}>{t('Desativada por padrão. Quando desativada, o processamento atual continua. O destino da transcrição não muda.')}</Text>
    </Card>
    {(loading || pending) && <ActivityIndicator accessibilityLabel={pending ? t('Salvando…') : t('Carregando…')} />}
    {settings && <Text testID="apple-dictation.availability" style={[ui.body, { color: c.muted }]}>{t(settings.available ? 'Reescrita com Apple disponível.' : 'Reescrita com Apple indisponível.')}</Text>}
    {!!settings?.message && <Text testID="apple-dictation.message" style={[ui.body, { color: c.muted }]}>{t(settings.message)}</Text>}
    {!!error && <Text testID="apple-dictation.error" accessibilityRole="alert" style={[ui.body, { color: c.danger }]}>{t(error)}</Text>}
    {!!error && <Button testID="apple-dictation.retry" disabled={loading || pending} onPress={() => void load()}>{t('Tentar carregar novamente')}</Button>}
    {busy && <Text style={[ui.small, { color: c.muted }]}>{t('Aguarde o fim da operação para alterar esta opção.')}</Text>}
    <Section title={t('Como funciona')}>
      <Text style={[ui.body, { color: c.text }]}>{t('Clarify transcribes the audio. Apple rewrites the text automatically, without opening an editor.')}</Text>
      <Text style={[ui.body, { color: c.text }]}>{t('A tradução para o idioma de saída selecionado ocorre no dispositivo. O resultado final volta ao resultado e ao histórico normais do Clarify.')}</Text>
    </Section>
    <Section title={t('Requisitos')}>
      <Text style={[ui.small, { color: c.muted }]}>{t('Download translation languages before dictating. Missing languages produce an error; no download window opens during dictation.')}</Text>
      <Text style={[ui.body, { color: c.text }]}>{t('Requer iOS 26, Apple Intelligence e o modo de ditado Natural. Use apenas os estilos Padrão, Formal ou Casual.')}</Text>
      <Text style={[ui.body, { color: c.text }]}>{t('Use dictation as usual, including from the Clarify keyboard in another app. No review or translation screen opens.')}</Text>
      <Text style={[ui.small, { color: c.muted }]}>{t('Selecione Natural e um estilo compatível em Saída do ditado antes de ativar.')}</Text>
      <Text style={[ui.small, { color: c.muted }]}>{t('Expanded snippets are preserved. Apple style and language changes are not applied to them in this build.')}</Text>
      <Text style={[ui.small, { color: c.muted }]}>{t('Use short recordings. Apple rewriting accepts up to 2,000 bytes of transcribed text.')}</Text>
    </Section>
    <Card>
      <NavigationRow testID="apple-dictation.output" title={t('Saída do ditado')} icon="textformat" onPress={() => router.push('/output')} />
    </Card>
  </ScrollView>;
}
