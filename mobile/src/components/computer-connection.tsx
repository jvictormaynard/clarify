import { Text, View } from 'react-native';
import { Button, Card, ui, usePalette } from './ui';
import { t } from '../i18n';
import { report, useClarify } from '../state/clarify';
import { computerStatus } from '../processing';

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
  const { account, accountBusy, computerCommand } = useClarify();
  const c = usePalette();
  const computer = account?.computer;
  const busy = accountBusy || !!computer?.busy;
  return <Card>
    <Text accessibilityRole="header" style={[ui.section, { color: c.text }]}>{t('Meu computador')}</Text>
    {!!computer?.computerName && <Text selectable style={[ui.body, { color: c.text }]}>{computer.computerName}</Text>}
    <Text testID="computer.status" accessibilityLiveRegion="polite" style={[ui.body, { color: c.muted }]}>{t(computerStatus(computer?.status))}</Text>
    <Text style={[ui.small, { color: c.muted }]}>{t('No Clarify do computador, abra a conexão com o iPhone e gere um QR. Mantenha os dois dispositivos na mesma rede Wi-Fi.')}</Text>
    <Text style={[ui.small, { color: c.muted }]}>{t('O computador processa seus ditados e textos com a configuração dele. Não é preciso entrar em uma conta Clarify.')}</Text>
    <Button primary testID="computer.scan" disabled={busy} onPress={() => void computerCommand('scan').catch(report)}>{t(computer?.paired ? 'Conectar outro computador' : 'Ler QR do computador')}</Button>
    {computer?.paired && <>
      <Button testID="computer.refresh" disabled={busy} onPress={() => void computerCommand('refresh').catch(report)}>{t('Verificar conexão')}</Button>
      <Button testID="computer.disconnect" disabled={busy} onPress={() => void computerCommand('disconnect').catch(report)}>{t('Desconectar computador')}</Button>
    </>}
  </Card>;
}

export function ComputerLibraryNotice() {
  const c = usePalette();
  return <Card><Text style={[ui.body, { color: c.text }]}>{t('Use o dicionário e os snippets configurados no computador.')}</Text>
    <Text style={[ui.small, { color: c.muted }]}>{t('Esta conexão não envia o dicionário, os snippets ou o histórico do iPhone para uma conta Clarify.')}</Text></Card>;
}
