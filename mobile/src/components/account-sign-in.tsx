import { t } from "../i18n";
import { useState } from 'react';
import { Text, TextInput } from 'react-native';
import { Button, TextButton, ui, usePalette } from './ui';
import type { AccountSnapshot } from '../../modules/clarify-core';
import { report } from '../state/clarify';

export function AccountSignIn({ account, busy, command }: {
  account: AccountSnapshot; busy: boolean;
  command: (action: string, value?: string) => Promise<void>;
}) {
  const c = usePalette();
  const [email, setEmail] = useState(account.email || '');
  const [code, setCode] = useState('');
  const [social, setSocial] = useState('');
  const [cancelling, setCancelling] = useState(false);
  const blocked = busy || !!social;
  const run = (action: string, value = '') => void command(action, value).catch(report);
  const input = { color: c.text, borderColor: c.controlBorder };
  const send = () => { if (!blocked && email.trim() && account.endpoint) run('login', email); };
  const signIn = (provider: string) => {
    if (blocked || !account.endpoint) return;
    setSocial(provider);
    void command('social', provider).catch(report).finally(() => { setSocial(''); setCancelling(false); });
  };
  const cancel = () => {
    setCancelling(true);
    void command('cancel-social').catch(error => { setCancelling(false); report(error); });
  };
  return account.pending ? <>
    <Text style={[ui.small, { color: c.muted }]}>{t("Digite o código enviado para {v0}. O código vale por 10 minutos.", { v0: account.email })}</Text>
    <TextInput selectionColor={c.text} testID="account.code" accessibilityLabel={t("Código da conta Clarify")} value={code} onChangeText={setCode} editable={!busy} textContentType="oneTimeCode" keyboardType="number-pad" maxLength={16} placeholder={t("Código")} placeholderTextColor={c.muted} style={[ui.input, input]} />
    <Button primary testID="account.verifyCode" loading={busy} disabled={!code.trim()} onPress={() => { run('confirm', code); setCode(''); }}>{t("Confirmar código")}</Button>
    <TextButton disabled={busy} onPress={() => run('logout')}>{t("Voltar")}</TextButton>
  </> : <>
    <Button loading={social === 'google'} disabled={blocked || !account.endpoint} onPress={() => signIn('google')}>{t("Continuar com Google")}</Button>
    <Button loading={social === 'microsoft'} disabled={blocked || !account.endpoint} onPress={() => signIn('microsoft')}>{t("Continuar com Microsoft")}</Button>
    <Button loading={social === 'github'} disabled={blocked || !account.endpoint} onPress={() => signIn('github')}>{t("Continuar com GitHub")}</Button>
    {social && <>
      <Text accessibilityLiveRegion="polite" style={[ui.small, { color: c.muted }]}>{t("Conclua a entrada na página do provedor.")}</Text>
      <TextButton disabled={cancelling} onPress={cancel}>{t("Cancelar")}</TextButton>
    </>}
    <Text style={[ui.small, { color: c.muted, textAlign: 'center' }]}>{t("Ou continue com seu e-mail")}</Text>
    <TextInput selectionColor={c.text} testID="account.email" accessibilityLabel={t("E-mail da conta Clarify")} value={email} onChangeText={setEmail} editable={!blocked} autoCapitalize="none" autoCorrect={false} keyboardType="email-address" textContentType="emailAddress" returnKeyType="go" onSubmitEditing={send} maxLength={254} placeholder={t("E-mail")} placeholderTextColor={c.muted} style={[ui.input, input]} />
    <Text style={[ui.small, { color: c.muted }]}>{t("Enviaremos um código para entrar ou criar sua conta. Você não precisa de senha.")}</Text>
    <Button primary testID="account.requestCode" loading={busy && !social} disabled={blocked || !email.trim() || !account.endpoint} onPress={send}>{t("Continuar")}</Button>
  </>;
}
