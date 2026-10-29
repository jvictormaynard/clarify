import { t, uiLanguage } from "../i18n";
import { useState, type ReactNode } from 'react';
import { ActivityIndicator, Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { Button, Card, ui, usePalette } from './ui';
import { isBusy, report, useClarify } from '../state/clarify';
import { formatUsageReset, usageProgress } from '../usage';
import { AccountSignIn } from './account-sign-in';

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
  const usage = usageProgress(account.usage);
  const percent = new Intl.NumberFormat(uiLanguage, { style: 'percent', maximumFractionDigits: 1 });
  const usageLabel = usage ? t("{v0} usados · {v1} restantes", {
    v0: percent.format(usage.used_percent / 100), v1: percent.format(usage.remaining_percent / 100),
  }) : '';
  const usageNotice = !usage ? "A cota semanal não está disponível. Atualize para tentar novamente."
    : usage.allocation_status === 'waiting' ? "Sua conta aguarda a próxima distribuição de cotas."
    : usage.allocation_status === 'unfunded' ? "Não há saldo de patrocínio para uma cota neste momento."
    : usage.allocation_status === 'inactive' ? "O processamento da conta está inativo."
    : usage.used_percent === 100 && usage.remaining_percent === 0 && usage.reserved_percent === 0
      ? "Você usou toda a sua cota semanal."
    : !usage.hosted_available ? "O processamento da conta está indisponível no momento." : '';
  const actionRow = (label: string, name: string, onPress: () => void, destructive = false) =>
    <Pressable testID={`account.${name}`} accessibilityRole="button" accessibilityState={{ disabled: !!busy, busy: action === name }} disabled={!!busy} onPress={onPress}
      style={({ pressed }) => ({ minHeight: 52, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', opacity: busy ? 0.5 : pressed ? 0.65 : 1 })}>
      <Text style={{ fontSize: 16, color: destructive ? c.danger : c.accent }}>{label}</Text>
      {action === name && <ActivityIndicator size="small" color={destructive ? c.danger : c.accent} />}
    </Pressable>;
  return <View style={{ gap: 20 }}>
    <Card style={{ gap: 8 }}>
      <Text style={[ui.small, { color: c.muted }]}>{t("Conta Clarify")}</Text>
      <Text selectable style={{ fontSize: 18, fontWeight: '600', color: c.text }}>{account.email}</Text>
      <Text style={[ui.small, { color: c.muted }]}>{t("Dicionário compartilhado entre seus dispositivos.")}</Text>
      {error}
    </Card>
    <Card style={{ gap: 14 }}>
      <Text accessibilityRole="header" style={[ui.section, { color: c.text, marginTop: 0 }]}>{t("Uso nesta semana")}</Text>
      {usage?.allocation_status === 'available' && <>
        <Text testID="account.weeklyUsage" style={{ fontSize: 22, fontWeight: '600', color: c.text, flexShrink: 1, fontVariant: ['tabular-nums'] }}>{usageLabel}</Text>
        <View accessibilityRole="progressbar" accessibilityLabel={t("Uso nesta semana")}
          accessibilityValue={{ min: 0, max: 100, now: usage.used_percent, text: usageLabel }}
          style={{ height: 8, borderRadius: 4, overflow: 'hidden', backgroundColor: c.line }}>
          <View style={{ width: `${usage.used_percent}%`, height: '100%', borderRadius: 4, backgroundColor: usage.used_percent >= 90 ? c.danger : c.accent }} />
        </View>
      </>}
      {usageNotice && <Text accessibilityRole="text" style={[ui.small, { color: c.muted }]}>{t(usageNotice)}</Text>}
      {!usage && <Button loading={action === 'refresh'} disabled={busy} onPress={() => command('refresh')}>{t("Retry")}</Button>}
      {usage && <Text testID="account.usageReset" style={[ui.small, { color: c.muted }]}>{t("Próxima renovação: {v0}.", { v0: formatUsageReset(usage.reset_at, uiLanguage) })}</Text>}
      <Text style={[ui.small, { color: c.muted }]}>{t("Sua cota semanal é individual e vale em todos os seus dispositivos. Ela fica fixa até a renovação.")}</Text>
      <Text style={[ui.small, { color: c.muted }]}>{t("Os patrocínios financiam as cotas semanais. A disponibilidade depende do saldo de patrocínio.")}</Text>
    </Card>
    <Text style={[ui.small, { color: c.muted }]}>{t("O Clarify processa áudio, texto e palavras ativas do dicionário.")}</Text>
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
