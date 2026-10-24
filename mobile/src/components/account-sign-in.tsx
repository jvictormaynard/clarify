import { t } from "../i18n";
import { useState } from 'react';
import { Text, TextInput } from 'react-native';
import { Button, TextButton, ui, usePalette } from './ui';
import type { AccountSnapshot } from '../../modules/clarify-core';

export function AccountSignIn({ account, busy, command }: {
  account: AccountSnapshot; busy: boolean;
  command: (action: string, value?: string) => void;
}) {
  const c = usePalette();
  const [email, setEmail] = useState(account.email || '');
  const [code, setCode] = useState('');
  const input = { color: c.text, borderColor: c.controlBorder };
  const send = () => { if (!busy && email.trim() && account.endpoint) command('login', email); };
  return account.pending ? <>
    <Text style={[ui.small, { color: c.muted }]}>{t("Digite o código enviado para {v0}. O código vale por 10 minutos.", { v0: account.email })}</Text>
    <TextInput selectionColor={c.text} testID="account.code" accessibilityLabel={t("Código da conta Clarify")} value={code} onChangeText={setCode} editable={!busy} textContentType="oneTimeCode" keyboardType="number-pad" maxLength={16} placeholder={t("Código")} placeholderTextColor={c.muted} style={[ui.input, input]} />
    <Button primary testID="account.verifyCode" loading={busy} disabled={!code.trim()} onPress={() => { command('confirm', code); setCode(''); }}>{t("Confirmar código")}</Button>
    <TextButton disabled={busy} onPress={() => command('logout')}>{t("Voltar")}</TextButton>
  </> : <>
    <TextInput selectionColor={c.text} testID="account.email" accessibilityLabel={t("E-mail da conta Clarify")} value={email} onChangeText={setEmail} editable={!busy} autoCapitalize="none" autoCorrect={false} keyboardType="email-address" textContentType="emailAddress" returnKeyType="go" onSubmitEditing={send} maxLength={254} placeholder={t("E-mail")} placeholderTextColor={c.muted} style={[ui.input, input]} />
    <Text style={[ui.small, { color: c.muted }]}>{t("Enviaremos um código para entrar ou criar sua conta. Você não precisa de senha.")}</Text>
    <Button primary testID="account.requestCode" loading={busy} disabled={!email.trim() || !account.endpoint} onPress={send}>{t("Continuar")}</Button>
  </>;
}
