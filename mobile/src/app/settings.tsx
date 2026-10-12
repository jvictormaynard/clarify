import { t } from "../i18n";
import { useState } from 'react';
import { router } from 'expo-router';
import { Alert, Linking, ScrollView, Text, TextInput } from 'react-native';
import Core from '../../modules/clarify-core';
import { Button, Card, ui, usePalette } from '../components/ui';
import { isBusy, report, useClarify } from '../state/clarify';

export default function Settings() {
  const c = usePalette();
  const { state, refresh, refreshAccount, activate, activating, keyboardEntry, keyboardToken, accountBusy, account, accountCommand } = useClarify();
  const [key, setKey] = useState('');
  const [saving, setSaving] = useState(false);
  const [server, setServer] = useState('');
  const [advanced, setAdvanced] = useState(false);
  const [action, setAction] = useState('');
  const busy = isBusy(state) || accountBusy || !!account?.busy || !!action;
  async function perform(name: string, operation: () => Promise<unknown>) {
    setAction(name);
    try { await operation(); }
    catch (error) { report(error); }
    finally { setAction(''); }
  }
  async function saveKey(value: string) {
    setSaving(true);
    try {
      await Core.setKey(value); await refresh(); await refreshAccount(); setKey('');
      if (keyboardEntry && value.trim()) { router.navigate('/'); await activate(keyboardToken); }
    } catch (error) { report(error); }
    finally { setSaving(false); }
  }
  return <ScrollView style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={ui.content} contentInsetAdjustmentBehavior="automatic" keyboardShouldPersistTaps="handled">
    {!(account?.managed || account?.signedIn) && <Card>
      <Text style={[ui.section, { color: c.text }]}>{t("Sua chave Groq")}</Text>
      <TextInput value={key} onChangeText={setKey} editable={!busy && !saving} secureTextEntry autoCapitalize="none" autoCorrect={false} accessibilityLabel={t("Chave de API do Groq")}
        placeholder={account?.hasGroqKey ? t("Digite outra chave para substituir") : 'gsk_…'} placeholderTextColor={c.muted} style={[ui.input, { color: c.text, borderColor: c.line }]} />
      <Text style={[ui.small, { color: c.muted }]}>{t("Sua chave fica no Keychain deste iPhone. O áudio, o texto e as palavras ativas do dicionário são enviados ao serviço escolhido por você para transcrição e reescrita. Ao salvar, você autoriza esse processamento.")}</Text>
      <Button loading={saving} disabled={busy || !key.trim()} onPress={() => void saveKey(key)}>{t("Salvar chave")}</Button>
      {account?.hasGroqKey && <Button disabled={saving || busy} destructive onPress={() => Alert.alert(t("Remover chave?"), t("O processamento com chave própria ficará indisponível."), [{ text: t("Cancelar"), style: 'cancel' }, { text: t("Remover"), style: 'destructive', onPress: () => void saveKey('') }])}>{t("Remover chave")}</Button>}
    </Card>}
    <Card>
      <Text style={[ui.section, { color: c.text }]}>{t("Microfone")}</Text>
      <Text style={[ui.body, { color: c.muted }]}>{t("{v0} Não desliga por inatividade. Cada gravação pode durar até 5 minutos.", { v0: state.sessionActive ? t('Ativo entre ditados.') : t('Desativado.') })}</Text>
      <Button loading={activating || action === 'microphone'} disabled={busy || !state.configured} onPress={() => void perform('microphone', () => state.sessionActive ? Core.deactivate().then(refresh) : activate())}>{state.sessionActive ? t("Desativar microfone") : t("Ativar microfone")}</Button>
    </Card>
    <Card>
      <Text style={[ui.section, { color: c.text }]}>{t("Teclado")}</Text>
      <Text style={[ui.body, { color: c.muted }]}>{t("Ajustes do iPhone → Geral → Teclado → Teclados → Adicionar Novo Teclado → Clarify. Depois, ative “Acesso Total”.")}</Text>
      <Text style={[ui.body, { color: c.muted }]}>{t("Use o globo para selecionar o Clarify. Ative o microfone pelo botão “Começar” do teclado.")}</Text>
      <Button onPress={() => void Linking.openSettings().catch(report)}>{t("Abrir Ajustes do iPhone")}</Button>
    </Card>
    <Card>
      <Text style={[ui.section, { color: c.text }]}>{t("Dados neste iPhone")}</Text>
      <Text style={[ui.small, { color: c.muted }]}>{t("O histórico guarda a transcrição original e o texto revisado neste iPhone. Ele não é sincronizado com a conta. Os áudios são removidos após o processamento. Sua chave de API fica no armazenamento seguro deste iPhone.")}</Text>
      <Button loading={action === 'history'} disabled={busy} destructive onPress={() => Alert.alert(t("Apagar todo o histórico?"), t("Esta ação remove todos os textos salvos neste iPhone. Seu dicionário e sua chave serão mantidos."), [{ text: t("Cancelar"), style: 'cancel' }, { text: t("Apagar"), style: 'destructive', onPress: () => void perform('history', () => Core.clearHistory().then(refresh)) }])}>{t("Apagar histórico")}</Button>
    </Card>
    {!(account?.managed || account?.signedIn) && <Card>
      <Button disabled={busy} onPress={() => { setServer(account?.endpoint || ''); setAdvanced(!advanced); }}>{t("Servidor próprio")}</Button>
      {advanced && <>
        <TextInput accessibilityLabel={t("Servidor Clarify")} value={server} onChangeText={setServer} editable={!busy} autoCapitalize="none" autoCorrect={false} keyboardType="url" placeholder="https://…" placeholderTextColor={c.muted} style={[ui.input, { color: c.text, borderColor: c.line }]} />
        <Button loading={action === 'server'} disabled={busy} onPress={() => void perform('server', () => accountCommand('configure', server))}>{t("Salvar servidor")}</Button>
      </>}
    </Card>}
  </ScrollView>;
}
