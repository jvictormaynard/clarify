import { t } from "../i18n";
import { useState } from 'react';
import { router } from 'expo-router';
import { Alert, Text } from 'react-native';
import { Button, Card, TextButton, ui, usePalette } from './ui';
import { isBusy, report, useClarify } from '../state/clarify';

export function AccountCard() {
  const c = usePalette();
  const { state, account, accountBusy, accountCommand } = useClarify();
  const busy = isBusy(state) || accountBusy || account?.busy;
  const [action, setAction] = useState('');
  const command = (action: string, value = '') => { setAction(action); void accountCommand(action, value).catch(report).finally(() => setAction('')); };
  if (!account) return null;
  const used = Math.ceil(((account.usage.used_ms || 0) + (account.usage.reserved_ms || 0)) / 60000);
  const limit = Math.floor((account.usage.limit_ms || 0) / 60000);
  return <Card>
    <Text style={[ui.section, { color: c.text }]}>{t("Conta Clarify")}</Text>
    <Text style={[ui.small, { color: c.muted }]}>{account.signedIn ? t("Seu dicionário e sua cota de uso são compartilhados com o computador.") : t("Entre para ditar sem chave de API e compartilhar seu dicionário com o computador.")}</Text>
    {account.error && <Text accessibilityRole="alert" style={[ui.small, { color: c.text }]}>{t(account.error)}</Text>}
    {!account.signedIn ? <>
      <Button disabled={busy} onPress={() => router.push('/sign-in')}>{t("Entrar ou criar conta")}</Button>
      {account.managed && !account.pending && <TextButton disabled={busy} onPress={() => command('logout')}>{t("Continuar sem conta")}</TextButton>}
    </> : <>
      <Text style={[ui.body, { color: c.text }]}>{account.email}</Text>
      <Text style={[ui.small, { color: c.muted }]}>{t("O Clarify gerencia os modelos e provedores da sua conta. Áudio, texto e palavras ativas do dicionário são processados pelo Clarify.")}</Text>
      {!account.hosted && <Button loading={action === 'hosted'} disabled={busy} onPress={() => command('hosted', '1')}>{t("Ativar processamento do Clarify")}</Button>}
      <Text style={[ui.body, { color: c.text }]}>{t("{v0} de {v1} minutos neste mês", { v0: used, v1: limit })}</Text>
      <Text style={[ui.small, { color: c.muted }]}>{t("Cota compartilhada com o desktop. Atualizada após cada processamento.")}</Text>
      <Text style={[ui.small, { color: c.muted }]}>{t("Suas palavras são sincronizadas automaticamente. Ao sair, o dicionário local volta a ser usado.")}</Text>
      {account.dictionaryConflict && <>
        <Text style={[ui.small, { color: c.muted }]}>{t("Escolha somente para as palavras alteradas nos dois dispositivos. As outras alterações serão combinadas.")}</Text>
        <Button loading={action === 'sync-local'} disabled={busy} onPress={() => command('sync-local')}>{t("Manter as versões deste iPhone")}</Button>
        <Button loading={action === 'sync-remote'} disabled={busy} onPress={() => command('sync-remote')}>{t("Usar as versões da conta")}</Button>
      </>}
      <Button loading={action === 'logout'} disabled={busy} onPress={() => command('logout')}>{t("Sair da conta")}</Button>
      <Button loading={action === 'delete'} disabled={busy} destructive onPress={() => Alert.alert(t("Excluir conta Clarify?"), t("Remove o dicionário compartilhado e o acesso ao serviço. Esta ação não pode ser desfeita. O histórico deste iPhone será mantido."), [{ text: t("Cancelar"), style: 'cancel' }, { text: t("Excluir conta"), style: 'destructive', onPress: () => command('delete') }])}>{t("Excluir conta")}</Button>
    </>}
  </Card>;
}
