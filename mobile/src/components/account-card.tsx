import { router } from 'expo-router';
import { Alert, Switch, Text, View } from 'react-native';
import { Button, Card, ui, usePalette } from './ui';
import { isBusy, report, useClarify } from '../state/clarify';

export function AccountCard() {
  const c = usePalette();
  const { state, account, accountBusy, accountCommand } = useClarify();
  const busy = isBusy(state) || accountBusy || account?.busy;
  const command = (action: string, value = '') => void accountCommand(action, value).catch(report);
  if (!account) return null;
  const used = Math.ceil(((account.usage.used_ms || 0) + (account.usage.reserved_ms || 0)) / 60000);
  const limit = Math.floor((account.usage.limit_ms || 0) / 60000);
  return <Card>
    <Text style={[ui.section, { color: c.text }]}>Conta Clarify</Text>
    <Text style={[ui.small, { color: c.muted }]}>{account.signedIn ? 'Seu dicionário e sua cota de uso são compartilhados com o computador.' : 'Entre para ditar sem chave de API e compartilhar seu dicionário com o computador.'}</Text>
    {account.error && <Text accessibilityRole="alert" style={[ui.small, { color: c.text }]}>{account.error}</Text>}
    {!account.signedIn ? <>
      <Button disabled={busy} onPress={() => router.push('/sign-in')}>Entrar ou criar conta</Button>
    </> : <>
      <Text style={[ui.body, { color: c.text }]}>{account.email}</Text>
      <View style={ui.row}><Text style={[ui.body, { color: c.text, flex: 1 }]}>Usar processamento do Clarify</Text><Switch accessibilityLabel="Usar processamento do Clarify" value={account.hosted} disabled={busy} onValueChange={value => command('hosted', value ? '1' : '0')} /></View>
      <Text style={[ui.small, { color: c.muted }]}>Com esta opção ativa, áudio e texto são enviados ao serviço Clarify e ao Groq. Com a opção desativada, o ditado usa sua chave Groq.</Text>
      <Text style={[ui.body, { color: c.text }]}>{used} de {limit} minutos neste mês</Text>
      <Text style={[ui.small, { color: c.muted }]}>Cota compartilhada com o desktop. Sua chave própria não consome esta cota.</Text>
      <Button disabled={busy} onPress={() => command('refresh')}>Atualizar consumo</Button>
      <Text style={[ui.small, { color: c.muted }]}>Ao conectar o dicionário, suas palavras serão combinadas com as palavras da conta. As próximas alterações serão sincronizadas ao salvar. Ao sair, o dicionário local volta a ser usado.</Text>
      <Button disabled={busy} onPress={() => command('sync')}>{account.syncEnabled ? 'Sincronizar dicionário' : 'Conectar dicionário'}</Button>
      {account.dictionaryConflict && <>
        <Text style={[ui.small, { color: c.muted }]}>Escolha somente para as palavras alteradas nos dois dispositivos. As outras alterações serão combinadas.</Text>
        <Button disabled={busy} onPress={() => command('sync-local')}>Manter as versões deste iPhone</Button>
        <Button disabled={busy} onPress={() => command('sync-remote')}>Usar as versões da conta</Button>
      </>}
      <Button disabled={busy} onPress={() => command('logout')}>Sair da conta</Button>
      <Button disabled={busy} destructive onPress={() => Alert.alert('Excluir conta Clarify?', 'Remove o dicionário compartilhado e o acesso ao serviço. Esta ação não pode ser desfeita. O histórico deste iPhone será mantido.', [{ text: 'Cancelar', style: 'cancel' }, { text: 'Excluir conta', style: 'destructive', onPress: () => command('delete') }])}>Excluir conta</Button>
    </>}
    {busy && <Text style={[ui.small, { color: c.muted }]}>Aguarde…</Text>}
  </Card>;
}
