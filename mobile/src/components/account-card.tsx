import { t, uiLanguage } from "../i18n";
import { useState } from 'react';
import { router } from 'expo-router';
import { ActivityIndicator, Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { Button, Card, TextButton, ui, usePalette } from './ui';
import { isBusy, report, useClarify } from '../state/clarify';
import { usageProgress } from '../usage';

export function AccountCard() {
  const c = usePalette();
  const { state, account, accountBusy, accountCommand } = useClarify();
  const busy = isBusy(state) || accountBusy || account?.busy;
  const [action, setAction] = useState('');
  const command = (action: string, value = '') => { setAction(action); void accountCommand(action, value).catch(report).finally(() => setAction('')); };
  if (!account) return null;
  const error = account.error && <Text accessibilityRole="alert" style={[ui.small, { color: c.text }]}>{t(account.error)}</Text>;
  if (!account.signedIn) return <Card>
      <Text style={[ui.section, { color: c.text }]}>{t("Conta Clarify")}</Text>
      <Text style={[ui.body, { color: c.muted }]}>{t("Entre para ditar sem chave de API e compartilhar seu dicionário com o computador.")}</Text>
      {error}
      <Button disabled={busy} onPress={() => router.push('/sign-in')}>{t("Entrar ou criar conta")}</Button>
      {account.managed && !account.pending && <TextButton disabled={busy} onPress={() => command('logout')}>{t("Continuar sem conta")}</TextButton>}
    </Card>;
  const usage = usageProgress(account.usage.used_ms, account.usage.limit_ms);
  const minutes = new Intl.NumberFormat(uiLanguage, { maximumFractionDigits: 1 });
  const percent = new Intl.NumberFormat(uiLanguage, { style: 'percent', maximumFractionDigits: 1 }).format(usage.percent / 100);
  const usageLabel = t("{v0} de {v1} min", { v0: minutes.format(usage.usedMinutes), v1: minutes.format(usage.limitMinutes) });
  const actionRow = (label: string, name: string, onPress: () => void, destructive = false) =>
    <Pressable accessibilityRole="button" accessibilityState={{ disabled: !!busy, busy: action === name }} disabled={!!busy} onPress={onPress}
      style={({ pressed }) => ({ minHeight: 52, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', opacity: busy ? 0.5 : pressed ? 0.65 : 1 })}>
      <Text style={{ fontSize: 16, color: destructive ? c.danger : c.accent }}>{label}</Text>
      {action === name && <ActivityIndicator size="small" color={destructive ? c.danger : c.accent} />}
    </Pressable>;
  return <View style={{ gap: 32, paddingTop: 8 }}>
    <View style={{ gap: 8 }}>
      <Text style={[ui.small, { color: c.muted }]}>{t("Conta Clarify")}</Text>
      <Text selectable style={{ fontSize: 18, fontWeight: '600', color: c.text }}>{account.email}</Text>
      <Text style={[ui.small, { color: c.muted }]}>{t("Dicionário compartilhado entre seus dispositivos.")}</Text>
      {error}
    </View>
    <View style={{ gap: 14 }}>
      <Text accessibilityRole="header" style={[ui.section, { color: c.text, marginTop: 0 }]}>{t("Uso neste mês")}</Text>
      <View style={ui.row}>
        <Text style={{ fontSize: 22, fontWeight: '600', color: c.text, flexShrink: 1, fontVariant: ['tabular-nums'] }}>{usageLabel}</Text>
        <Text style={[ui.body, { color: c.muted, fontVariant: ['tabular-nums'] }]}>{percent}</Text>
      </View>
      <View accessibilityRole="progressbar" accessibilityLabel={t("Uso neste mês")}
        accessibilityValue={{ min: 0, max: 100, now: usage.percent, text: usageLabel }}
        style={{ height: 8, borderRadius: 4, overflow: 'hidden', backgroundColor: c.line }}>
        <View style={{ width: `${usage.percent}%`, height: '100%', borderRadius: 4, backgroundColor: usage.percent >= 90 ? c.danger : c.accent }} />
      </View>
      <Text style={[ui.small, { color: c.muted }]}>{t("Cota compartilhada com o computador.")}</Text>
    </View>
    <Text style={[ui.small, { color: c.muted }]}>{t("O Clarify processa áudio, texto e palavras ativas do dicionário.")}</Text>
    {account.dictionaryConflict && <Card>
        <Text style={[ui.small, { color: c.muted }]}>{t("Escolha somente para as palavras alteradas nos dois dispositivos. As outras alterações serão combinadas.")}</Text>
        <Button loading={action === 'sync-local'} disabled={busy} onPress={() => command('sync-local')}>{t("Manter as versões deste iPhone")}</Button>
        <Button loading={action === 'sync-remote'} disabled={busy} onPress={() => command('sync-remote')}>{t("Usar as versões da conta")}</Button>
    </Card>}
    <View style={{ borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: c.line }}>
      {actionRow(t("Sair da conta"), 'logout', () => command('logout'))}
      <View style={{ height: StyleSheet.hairlineWidth, backgroundColor: c.line }} />
      {actionRow(t("Excluir conta"), 'delete', () => Alert.alert(t("Excluir conta Clarify?"), t("Remove o dicionário compartilhado e o acesso ao serviço. Esta ação não pode ser desfeita. O histórico deste iPhone será mantido."), [{ text: t("Cancelar"), style: 'cancel' }, { text: t("Excluir conta"), style: 'destructive', onPress: () => command('delete') }]), true)}
    </View>
  </View>;
}
