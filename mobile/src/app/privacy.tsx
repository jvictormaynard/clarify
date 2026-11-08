import { t } from '../i18n';
import { useState } from 'react';
import { Alert, ScrollView, Text } from 'react-native';
import Core from '../../modules/clarify-core';
import { Button, Section, ui, usePalette } from '../components/ui';
import { isBusy, report, useClarify } from '../state/clarify';

export default function Details() {
  const c = usePalette();
  const { state, refresh, accountBusy, account } = useClarify();
  const [action, setAction] = useState('');
  const busy = isBusy(state) || accountBusy || !!account?.busy || !!action;
  async function perform(name: string, operation: () => Promise<unknown>) {
    setAction(name);
    try { await operation(); } catch (error) { report(error); } finally { setAction(''); }
  }
  return <ScrollView style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={ui.content} contentInsetAdjustmentBehavior="automatic" keyboardShouldPersistTaps="handled">
    <Section title={t('Histórico e privacidade')}>
      <Text style={[ui.small, { color: c.muted }]}>{t(account?.mode === 'computer' ? 'O histórico desta conexão fica neste iPhone. O áudio é removido após o processamento.' : "Novos ditados da conta são sincronizados entre seus dispositivos. Registros antigos e ditados sem conta permanecem neste iPhone. Os áudios são removidos após o processamento.")}</Text>
      <Button loading={action === 'history'} disabled={busy || !account} destructive onPress={() => Alert.alert(t("Apagar todo o histórico?"), account?.mode === 'computer' ? t('Esta ação apaga somente o histórico desta conexão neste iPhone.') : account?.historyAccount ? t("Esta ação apaga o histórico da conta em todos os dispositivos e os registros locais deste iPhone. Seu dicionário será mantido.") : t("Esta ação remove todos os textos salvos neste iPhone. Seu dicionário e sua chave serão mantidos."), [{ text: t("Cancelar"), style: 'cancel' }, { text: t("Apagar"), style: 'destructive', onPress: () => void perform('history', () => Core.clearHistory(account?.historyContext ?? '').then(refresh)) }])}>{t("Apagar histórico")}</Button>
    </Section>
  </ScrollView>;
}
