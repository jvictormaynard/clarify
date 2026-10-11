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
  const busy = isBusy(state) || accountBusy || !!account?.busy;
  async function saveKey(value: string) {
    setSaving(true);
    try {
      await Core.setKey(value); await refresh(); await refreshAccount(); setKey('');
      if (keyboardEntry && value.trim()) { router.navigate('/'); await activate(keyboardToken); }
    } catch (error) { report(error); }
    finally { setSaving(false); }
  }
  return <ScrollView style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={ui.content} contentInsetAdjustmentBehavior="automatic" keyboardShouldPersistTaps="handled">
    <Card>
      <Text style={[ui.section, { color: c.text }]}>Sua chave Groq</Text>
      <TextInput value={key} onChangeText={setKey} editable={!busy && !saving} secureTextEntry autoCapitalize="none" autoCorrect={false} accessibilityLabel="Chave de API do Groq"
        placeholder={account?.hasGroqKey ? 'Digite outra chave para substituir' : 'gsk_…'} placeholderTextColor={c.muted} style={[ui.input, { color: c.text, borderColor: c.line }]} />
      <Text style={[ui.small, { color: c.muted }]}>Sua chave fica no Keychain deste iPhone. O áudio, o texto e as palavras ativas do dicionário são enviados diretamente ao Groq para transcrição e reescrita. Ao salvar, você autoriza esse processamento.</Text>
      <Button disabled={saving || busy || !key.trim()} onPress={() => void saveKey(key)}>{saving ? 'Salvando…' : 'Salvar chave'}</Button>
      {account?.hasGroqKey && <Button disabled={saving || busy} destructive onPress={() => Alert.alert('Remover chave?', 'O processamento com chave própria ficará indisponível.', [{ text: 'Cancelar', style: 'cancel' }, { text: 'Remover', style: 'destructive', onPress: () => void saveKey('') }])}>Remover chave</Button>}
    </Card>
    <Card>
      <Text style={[ui.section, { color: c.text }]}>Microfone</Text>
      <Text style={[ui.body, { color: c.muted }]}>{state.sessionActive ? 'Ativo entre ditados.' : 'Desativado.'} A sessão termina após 5 minutos sem uso. Cada gravação pode durar até 5 minutos.</Text>
      <Button disabled={busy || activating || !state.configured} onPress={() => void (state.sessionActive ? Core.deactivate().then(refresh) : activate()).catch(report)}>{activating ? 'Ativando…' : state.sessionActive ? 'Desativar microfone' : 'Ativar microfone'}</Button>
    </Card>
    <Card>
      <Text style={[ui.section, { color: c.text }]}>Teclado</Text>
      <Text style={[ui.body, { color: c.muted }]}>Ajustes do iPhone → Geral → Teclado → Teclados → Adicionar Novo Teclado → Clarify. Depois, ative “Acesso Total”.</Text>
      <Text style={[ui.body, { color: c.muted }]}>Use o globo para selecionar o Clarify. Ative o microfone pelo botão “Começar” do teclado.</Text>
      <Button onPress={() => void Linking.openSettings().catch(report)}>Abrir Ajustes do iPhone</Button>
    </Card>
    <Card>
      <Text style={[ui.section, { color: c.text }]}>Dados neste iPhone</Text>
      <Text style={[ui.small, { color: c.muted }]}>O histórico guarda a transcrição original e o texto revisado neste iPhone. Ele não é sincronizado com a conta. Os áudios são removidos após o processamento. Sua chave Groq não é enviada ao servidor Clarify.</Text>
      <Button disabled={busy} destructive onPress={() => Alert.alert('Apagar todo o histórico?', 'Esta ação remove todos os textos salvos neste iPhone. Seu dicionário e sua chave serão mantidos.', [{ text: 'Cancelar', style: 'cancel' }, { text: 'Apagar', style: 'destructive', onPress: () => void Core.clearHistory().then(refresh).catch(report) }])}>Apagar histórico</Button>
    </Card>
    {!account?.signedIn && <Card>
      <Button disabled={busy} onPress={() => { setServer(account?.endpoint || ''); setAdvanced(!advanced); }}>Servidor próprio</Button>
      {advanced && <>
        <TextInput accessibilityLabel="Servidor Clarify" value={server} onChangeText={setServer} editable={!busy} autoCapitalize="none" autoCorrect={false} keyboardType="url" placeholder="https://…" placeholderTextColor={c.muted} style={[ui.input, { color: c.text, borderColor: c.line }]} />
        <Button disabled={busy} onPress={() => void accountCommand('configure', server).catch(report)}>Salvar servidor</Button>
      </>}
    </Card>}
  </ScrollView>;
}
