import { t } from '../i18n';
import { useState } from 'react';
import { Linking, ScrollView, Text } from 'react-native';
import Core from '../../modules/clarify-core';
import { Button, Section, ui, usePalette } from '../components/ui';
import { isBusy, report, useClarify } from '../state/clarify';

export default function Details() {
  const c = usePalette();
  const { state, refresh, activate, activating, accountBusy, account } = useClarify();
  const [action, setAction] = useState('');
  const busy = isBusy(state) || accountBusy || !!account?.busy || !!action;
  async function perform(name: string, operation: () => Promise<unknown>) {
    setAction(name);
    try { await operation(); } catch (error) { report(error); } finally { setAction(''); }
  }
  return <ScrollView style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={ui.content} contentInsetAdjustmentBehavior="automatic" keyboardShouldPersistTaps="handled">
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
  </ScrollView>;
}
