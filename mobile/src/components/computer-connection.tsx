import { useState } from 'react';
import { ActivityIndicator, Alert, Text, View } from 'react-native';
import { Button, Card, TextButton, ui, usePalette } from './ui';
import { t } from '../i18n';
import { report, useClarify } from '../state/clarify';
import { computerStatus } from '../processing';
import { AccountSignIn } from './account-sign-in';
import type { AccountSnapshot } from '../../modules/clarify-core';

export function ProcessingChoice() {
  const { account, accountBusy, computerCommand } = useClarify();
  const c = usePalette();
  const busy = accountBusy || !!account?.busy;
  return <View style={{ gap: 10 }}>
    <Text style={[ui.small, { color: c.muted }]}>{t('Processar com')}</Text>
    <View style={{ flexDirection: 'row', gap: 10 }}>
      <View style={{ flex: 1 }}><Button testID="processing.hosted" primary={account?.mode !== 'computer'} disabled={busy} onPress={() => void computerCommand('hosted').catch(report)}>{t('Conta Clarify')}</Button></View>
      <View style={{ flex: 1 }}><Button testID="processing.computer" primary={account?.mode === 'computer'} disabled={busy} onPress={() => void computerCommand('computer').catch(report)}>{t('Meu computador')}</Button></View>
    </View>
  </View>;
}

export function ComputerConnectionCard() {
  const { account, accountBusy, computerCommand, accountCommand } = useClarify();
  const c = usePalette();
  const [managing, setManaging] = useState(false);
  const computer = account?.computer;
  const busy = accountBusy || !!computer?.busy;
  const paired = computer?.paired === true;
  const refresh = () => void computerCommand('refresh').catch(report);
  const disconnect = () => Alert.alert(t('Desconectar computador?'),
    t('Para conectar novamente, será preciso ler outro QR.'), [
      { text: t('Cancelar'), style: 'cancel' },
      { text: t('Desconectar'), style: 'destructive', onPress: () => void computerCommand('disconnect').catch(report) },
    ]);
  return <View style={{ gap: 16 }}>
    <Card>
      <Text accessibilityRole="header" style={[ui.section, { color: c.text }]}>{paired ? computer.computerName || t('Meu computador') : t('Conectar computador')}</Text>
      {paired ? <>
        <Text testID="computer.status" accessibilityLiveRegion="polite" style={[ui.body, { color: c.text }]}>{t(computerStatus(computer.status))}</Text>
        {computer.status === 'offline' && <Text style={[ui.small, { color: c.muted }]}>{t('Abra o Clarify no computador e mantenha-o ligado.')}</Text>}
        <Button testID="computer.refresh" primary={computer.status === 'offline'} loading={!!computer.busy && computer.remoteStatus !== 'registering'} disabled={busy} onPress={refresh}>{t('Verificar conexão')}</Button>
        <TextButton testID="computer.manage" disabled={busy} expanded={managing} onPress={() => setManaging(!managing)}>{t(managing ? 'Ocultar opções' : 'Gerenciar conexão')}</TextButton>
        {managing && <>
          <Button testID="computer.scan" disabled={busy} onPress={() => void computerCommand('scan').catch(report)}>{t('Conectar outro computador')}</Button>
          <TextButton testID="computer.disconnect" disabled={busy} onPress={disconnect}>{t('Desconectar computador')}</TextButton>
        </>}
      </> : <>
        <Text style={[ui.body, { color: c.text }]}>{t('No PC, abra Conectar celular e gere um QR.')}</Text>
        <Text style={[ui.small, { color: c.muted }]}>{t('Na primeira conexão, use a mesma rede Wi-Fi.')}</Text>
        <Button primary testID="computer.scan" disabled={busy} onPress={() => void computerCommand('scan').catch(report)}>{t('Ler QR do computador')}</Button>
      </>}
    </Card>
    {paired && account && <RemoteAccess account={account} busy={busy} accountCommand={accountCommand} refresh={refresh} />}
  </View>;
}

function RemoteAccess({ account, busy, accountCommand, refresh }: {
  account: AccountSnapshot; busy: boolean;
  accountCommand: (action: string, value?: string) => Promise<void>; refresh: () => void;
}) {
  const c = usePalette();
  const computer = account.computer!;
  const remote = computer.remoteStatus ?? 'unavailable';
  const reachable = ['ready', 'not_ready'].includes(computer.status);
  const authorization = ['account_required', 'authorization_required'].includes(remote);
  const renew = remote === 'account_required' && account.signedIn;
  const message = remote === 'registered' ? 'Acesso pela internet configurado.'
    : remote === 'registering' ? 'Ativando acesso pela internet…'
    : ['failed', 'cancelled'].includes(remote) ? 'Não foi possível confirmar a ativação. A conexão local foi mantida.'
    : ['unsupported', 'disabled'].includes(remote) ? 'Atualize o Clarify para usar fora do Wi-Fi.'
    : !reachable ? 'Conecte o iPhone à mesma rede do PC para configurar.'
    : renew ? 'Entre novamente para autorizar esta conexão. O pareamento será mantido.'
    : authorization && !account.signedIn ? 'Entre com uma conta gratuita para autorizar a conexão.'
    : 'Use seus modelos do PC também com os dados móveis.';
  return <Card>
    <Text accessibilityRole="header" style={[ui.section, { color: c.text }]}>{t('Fora do Wi-Fi')}</Text>
    <Text testID="computer.remote-status" accessibilityLiveRegion="polite" style={[ui.body, { color: c.text }]}>{t(message)}</Text>
    {remote === 'registered' && <Text style={[ui.small, { color: c.muted }]}>{t('O computador precisa continuar ligado, com o Clarify aberto.')}</Text>}
    {remote === 'registering' && <ActivityIndicator accessibilityLabel={t('Ativando acesso pela internet…')} color={c.text} />}
    {authorization && reachable && (renew
      ? <Button primary testID="computer.reauthenticate" disabled={busy} loading={busy} onPress={() => void accountCommand('logout').catch(report)}>{t('Entrar novamente')}</Button>
      : !account.signedIn ? <AccountSignIn account={account} busy={busy} command={accountCommand} />
      : <Button primary testID="computer.authorize-remote" disabled={busy || !reachable} onPress={() => void accountCommand('connect').catch(report)}>{t('Ativar acesso pela internet')}</Button>)}
    {['failed', 'cancelled', 'unavailable'].includes(remote) && <Button primary={reachable} testID="computer.remote-recover" disabled={busy} onPress={refresh}>{t('Verificar ativação')}</Button>}
  </Card>;
}

export function ComputerLibraryNotice() {
  const c = usePalette();
  return <Card><Text style={[ui.body, { color: c.text }]}>{t('Use o dicionário e os snippets configurados no computador.')}</Text>
    <Text style={[ui.small, { color: c.muted }]}>{t('Esta conexão não envia o dicionário, os snippets ou o histórico do iPhone para uma conta Clarify.')}</Text></Card>;
}
