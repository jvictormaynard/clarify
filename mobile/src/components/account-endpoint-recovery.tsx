import { Alert, Text, View } from 'react-native';
import type { AccountSnapshot } from '../../modules/clarify-core';
import { t } from '../i18n';
import { report } from '../state/clarify';
import { Button, ui, usePalette } from './ui';

export function AccountEndpointRecovery({ account, busy, command }: {
  account: AccountSnapshot; busy: boolean;
  command: (action: string, value?: string) => Promise<void>;
}) {
  const c = usePalette();
  if (!account.endpointRecovery) return null;
  const confirm = () => Alert.alert(t('Usar o servidor de produção?'),
    t('Será necessário entrar novamente. O histórico do servidor anterior será mantido separado neste iPhone.'), [
      { text: t('Cancelar'), style: 'cancel' },
      { text: t('Usar servidor de produção'), onPress: () => void command('recover-endpoint').catch(report) },
    ]);
  return <View style={{ gap: 12 }}>
    <Text accessibilityRole="alert" style={[ui.body, { color: c.text }]}>{t('Esta conta usa o servidor de desenvolvimento: {v0}.', { v0: new URL(account.endpoint).hostname })}</Text>
    <Button testID="account.recoverEndpoint" disabled={busy} onPress={confirm}>{t('Usar servidor de produção')}</Button>
  </View>;
}
