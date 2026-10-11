import { useState } from 'react';
import { Text, TextInput, View } from 'react-native';
import { Button, ui, usePalette } from './ui';
import type { AccountSnapshot } from '../../modules/clarify-core';

export function AccountSignIn({ account, busy, command, intent }: {
  account: AccountSnapshot; busy: boolean;
  command: (action: string, value?: string) => void;
  intent?: 'login' | 'signup';
}) {
  const c = usePalette();
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const input = { color: c.text, borderColor: c.line };
  return account.pending ? <>
    <Text style={[ui.small, { color: c.muted }]}>Digite o código enviado para {account.email}. O código vale por 10 minutos.</Text>
    <TextInput accessibilityLabel="Código da conta Clarify" value={code} onChangeText={setCode} editable={!busy} textContentType="oneTimeCode" keyboardType="number-pad" maxLength={16} placeholder="Código" placeholderTextColor={c.muted} style={[ui.input, input]} />
    <Button disabled={busy || !code.trim()} onPress={() => { command('confirm', code); setCode(''); }}>Confirmar código</Button>
    <Button disabled={busy} onPress={() => command('logout')}>Cancelar entrada</Button>
  </> : <>
    <Text style={[ui.small, { color: c.muted }]}>Receba um código por e-mail. Você não precisa criar uma senha.</Text>
    <TextInput accessibilityLabel="E-mail da conta Clarify" value={email} onChangeText={setEmail} editable={!busy} autoCapitalize="none" autoCorrect={false} keyboardType="email-address" textContentType="emailAddress" placeholder="E-mail" placeholderTextColor={c.muted} style={[ui.input, input]} />
    <View style={ui.row}>
      {intent !== 'signup' && <Button disabled={busy || !email.trim() || !account.endpoint} onPress={() => command('login', email)}>Entrar</Button>}
      {intent !== 'login' && <Button disabled={busy || !email.trim() || !account.endpoint} onPress={() => command('signup', email)}>Criar conta</Button>}
    </View>
  </>;
}
