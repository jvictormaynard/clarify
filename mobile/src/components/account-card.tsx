import { t } from "../i18n";
import { useState, type ReactNode } from 'react';
import { ActivityIndicator, Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { Button, Card, ui, usePalette } from './ui';
import { isBusy, report, useClarify } from '../state/clarify';
import { AccountSignIn } from './account-sign-in';
import { AccountEndpointRecovery } from './account-endpoint-recovery';

export function AccountCard({ children }: { children?: ReactNode }) {
  const c = usePalette();
  const { state, account, accountBusy, accountCommand } = useClarify();
  const busy = isBusy(state) || accountBusy || account?.busy;
  const [action, setAction] = useState('');
  const command = (action: string, value = '') => { setAction(action); void accountCommand(action, value).catch(report).finally(() => setAction('')); };
  if (!account) return null;
  const error = account.error && <Text accessibilityRole="alert" style={[ui.small, { color: c.text }]}>{t(account.error)}</Text>;
  if (!account.signedIn) return <Card>
      <Text style={[ui.section, { color: c.text }]}>{t("Conta Clarify")}</Text>
      <Text style={[ui.body, { color: c.muted }]}>{t("Entre ou crie sua conta Clarify.")}</Text>
      {error}
      <AccountSignIn account={account} busy={!!busy} command={accountCommand} />
    </Card>;
  const actionRow = (label: string, name: string, onPress: () => void, destructive = false) =>
    <Pressable testID={`account.${name}`} accessibilityRole="button" accessibilityState={{ disabled: !!busy, busy: action === name }} disabled={!!busy} onPress={onPress}
      style={({ pressed }) => ({ minHeight: 52, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', opacity: busy ? 0.5 : pressed ? 0.65 : 1 })}>
      <Text style={{ fontSize: 16, color: destructive ? c.danger : c.accent }}>{label}</Text>
      {action === name && <ActivityIndicator size="small" color={destructive ? c.danger : c.accent} />}
    </Pressable>;
  return <View style={{ gap: 20 }}>
    {account.endpointRecovery && <Card><AccountEndpointRecovery account={account} busy={!!busy} command={accountCommand} /></Card>}
    <Card style={{ gap: 8 }}>
      <Text style={[ui.small, { color: c.muted }]}>{t("Conta Clarify")}</Text>
      <Text selectable style={{ fontSize: 18, fontWeight: '600', color: c.text }}>{account.email}</Text>
      <Text style={[ui.small, { color: c.muted }]}>{t("Dicionário compartilhado entre seus dispositivos.")}</Text>
      {error}
    </Card>
    {account.dictionaryConflict && <Card>
        <Text style={[ui.small, { color: c.muted }]}>{t("Escolha somente para as palavras ou snippets alterados nos dois dispositivos. As outras alterações serão combinadas.")}</Text>
        <Button loading={action === 'sync-local'} disabled={busy} onPress={() => command('sync-local')}>{t("Manter as versões deste iPhone")}</Button>
        <Button loading={action === 'sync-remote'} disabled={busy} onPress={() => command('sync-remote')}>{t("Usar as versões da conta")}</Button>
    </Card>}
    {children}
    <Card>
      {actionRow(t("Sair da conta"), 'logout', () => command('logout'))}
      <View style={{ height: StyleSheet.hairlineWidth, backgroundColor: c.line }} />
      {actionRow(t("Excluir conta"), 'delete', () => Alert.alert(t("Excluir conta Clarify?"), t("Excluir a conta remove o dicionário, os snippets e o histórico compartilhados e o acesso ao serviço. Esta ação não pode ser desfeita. Os registros locais serão mantidos."), [{ text: t("Cancelar"), style: 'cancel' }, { text: t("Excluir conta"), style: 'destructive', onPress: () => command('delete') }]), true)}
    </Card>
  </View>;
}
