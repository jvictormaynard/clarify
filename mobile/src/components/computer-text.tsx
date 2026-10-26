import { useState } from 'react';
import { Text, TextInput, View } from 'react-native';
import Core from '../../modules/clarify-core';
import { t, uiLanguage } from '../i18n';
import { isBusy, report, useClarify } from '../state/clarify';
import { Button, Card, ui, usePalette } from './ui';

export function ComputerText() {
  const c = usePalette();
  const { state, account, refresh } = useClarify();
  const [text, setText] = useState('');
  const [language, setLanguage] = useState(uiLanguage);
  const [sending, setSending] = useState(false);
  const busy = sending || isBusy(state);
  async function process(action: 'rewrite' | 'translate') {
    setSending(true);
    try { await Core.processComputerText(action, text, language, account?.historyContext ?? ''); await refresh(); }
    catch (error) { report(error); }
    finally { setSending(false); }
  }
  if (account?.mode !== 'computer') return null;
  return <Card>
    <Text style={[ui.section, { color: c.text }]}>{t('Texto pelo computador')}</Text>
    <TextInput testID="computer.text" accessibilityLabel={t('Texto para processar')} multiline value={text} onChangeText={setText} editable={!busy}
      maxLength={8000} placeholder={t('Cole ou escreva o texto')} placeholderTextColor={c.muted}
      style={[ui.input, { color: c.text, borderColor: c.controlBorder, minHeight: 100 }]} />
    <Text style={[ui.small, { color: c.muted }]}>{t('Idioma do resultado')}</Text>
    <View style={{ flexDirection: 'row', gap: 8 }}>
      {(['pt', 'en', 'es'] as const).map(value => <View key={value} style={{ flex: 1 }}><Button disabled={busy} primary={language === value} onPress={() => setLanguage(value)}>{({ pt: 'Português', en: 'English', es: 'Español' })[value]}</Button></View>)}
    </View>
    <Button disabled={busy || !text.trim()} onPress={() => void process('rewrite')}>{t('Reescrever')}</Button>
    <Button disabled={busy || !text.trim()} onPress={() => void process('translate')}>{t('Traduzir')}</Button>
    {isBusy(state) && state.operationID && <Button onPress={() => void Core.command('cancel', state.operationID!, state.processingContext ?? '').catch(report)}>{t('Cancelar')}</Button>}
    {state.text && !isBusy(state) && <>
      <Text selectable style={[ui.body, { color: c.text }]}>{state.text}</Text>
      <Button onPress={() => void Core.copyResult().catch(report)}>{t('Copiar')}</Button>
    </>}
    {state.phase === 'error' && state.message && <Text accessibilityRole="alert" style={[ui.body, { color: c.muted }]}>{t(state.message)}</Text>}
  </Card>;
}
