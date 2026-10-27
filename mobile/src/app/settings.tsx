import { t } from "../i18n";
import { useState } from 'react';
import { router } from 'expo-router';
import { Alert, Linking, ScrollView, Text } from 'react-native';
import Core from '../../modules/clarify-core';
import { Button, NavigationRow, Section, ui, usePalette } from '../components/ui';
import { isBusy, report, useClarify } from '../state/clarify';

export default function Settings() {
  const c = usePalette();
  const { state, refresh, activate, activating, accountBusy, account } = useClarify();
  const [action, setAction] = useState('');
  const busy = isBusy(state) || accountBusy || !!account?.busy || !!action;
  async function perform(name: string, operation: () => Promise<unknown>) {
    setAction(name);
    try { await operation(); }
    catch (error) { report(error); }
    finally { setAction(''); }
  }
  return <ScrollView style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={[ui.content, { gap: 28 }]} contentInsetAdjustmentBehavior="automatic" keyboardShouldPersistTaps="handled">
    <Section title={t('Como usar')}>
      <NavigationRow title={t('Configurar e testar o teclado')} icon="keyboard" onPress={() => router.push('/guide')} />
    </Section>
    <Section title={t('Microfone')}>
      <Text style={[ui.body, { color: c.muted }]}>{t("{v0} Não desliga por inatividade. Cada gravação pode durar até 5 minutos.", { v0: state.sessionActive ? t('Ativo entre ditados.') : t('Desativado.') })}</Text>
      <Button loading={activating || action === 'microphone'} disabled={busy || !state.configured} onPress={() => void perform('microphone', () => state.sessionActive ? Core.deactivate().then(refresh) : activate())}>{state.sessionActive ? t("Desativar microfone") : t("Ativar microfone")}</Button>
    </Section>
    <Section title={t('Teclado')}>
      <Text style={[ui.body, { color: c.muted }]}>{t("Ajustes do iPhone → Geral → Teclado → Teclados → Adicionar Novo Teclado → Clarify. Depois, ative “Acesso Total”.")}</Text>
      <Text style={[ui.body, { color: c.muted }]}>{t("Use o globo para selecionar o Clarify. Ative o microfone pelo botão “Começar” do teclado.")}</Text>
      <Button onPress={() => void Linking.openSettings().catch(report)}>{t("Abrir Ajustes do iPhone")}</Button>
      {Core.keyboardDiagnosticAvailable && <Button loading={action === 'keyboard-test'} disabled={busy} onPress={() => void perform('keyboard-test', () => Core.openKeyboardDiagnostic())}>{t("Teste de abertura do teclado")}</Button>}
    </Section>
    <Section title={t('Histórico e privacidade')}>
      <Text style={[ui.small, { color: c.muted }]}>{t(account?.mode === 'computer' ? 'O histórico desta conexão fica neste iPhone. O áudio é removido após o processamento.' : "Novos ditados da conta são sincronizados entre seus dispositivos. Registros antigos e ditados sem conta permanecem neste iPhone. Os áudios são removidos após o processamento.")}</Text>
      <Button loading={action === 'history'} disabled={busy || !account} destructive onPress={() => Alert.alert(t("Apagar todo o histórico?"), account?.mode === 'computer' ? t('Esta ação apaga somente o histórico desta conexão neste iPhone.') : account?.historyAccount ? t("Esta ação apaga o histórico da conta em todos os dispositivos e os registros locais deste iPhone. Seu dicionário será mantido.") : t("Esta ação remove todos os textos salvos neste iPhone. Seu dicionário e sua chave serão mantidos."), [{ text: t("Cancelar"), style: 'cancel' }, { text: t("Apagar"), style: 'destructive', onPress: () => void perform('history', () => Core.clearHistory(account?.historyContext ?? '').then(refresh)) }])}>{t("Apagar histórico")}</Button>
    </Section>
  </ScrollView>;
}
