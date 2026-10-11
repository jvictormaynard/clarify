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
  const input = { color: c.text, borderColor: c.line };
  const send = () => { if (!busy && email.trim() && account.endpoint) command('login', email); };
  return account.pending ? <>
    <Text style={[ui.small, { color: c.muted }]}>Digite o código enviado para {account.email}. O código vale por 10 minutos.</Text>
    <TextInput accessibilityLabel="Código da conta Clarify" value={code} onChangeText={setCode} editable={!busy} textContentType="oneTimeCode" keyboardType="number-pad" maxLength={16} placeholder="Código" placeholderTextColor={c.muted} style={[ui.input, input]} />
    <Button disabled={busy || !code.trim()} onPress={() => { command('confirm', code); setCode(''); }}>Confirmar código</Button>
    <TextButton disabled={busy} onPress={() => command('logout')}>Usar outro e-mail</TextButton>
  </> : <>
    <TextInput accessibilityLabel="E-mail da conta Clarify" value={email} onChangeText={setEmail} editable={!busy} autoCapitalize="none" autoCorrect={false} keyboardType="email-address" textContentType="emailAddress" returnKeyType="go" onSubmitEditing={send} maxLength={254} placeholder="E-mail" placeholderTextColor={c.muted} style={[ui.input, input]} />
    <Text style={[ui.small, { color: c.muted }]}>Enviaremos um código para entrar ou criar sua conta. Você não precisa de senha.</Text>
    <Button disabled={busy || !email.trim() || !account.endpoint} onPress={send}>Continuar</Button>
  </>;
}
