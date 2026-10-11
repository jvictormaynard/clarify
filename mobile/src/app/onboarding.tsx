import { t } from "../i18n";
import { useState } from 'react';
import { ActivityIndicator, Linking, ScrollView, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Core, { type AccountSnapshot } from '../../modules/clarify-core';
import { AccountSignIn } from '../components/account-sign-in';
import { ClarifyLogo } from '../components/clarify-logo';
import { Button, Card, TextButton, Title, ui, usePalette } from '../components/ui';
import { report, useClarify } from '../state/clarify';

export default function Onboarding() {
  const c = usePalette();
  const { account, refreshAccount } = useClarify();
  if (!account) return <SafeAreaView style={{ flex: 1, backgroundColor: c.background, justifyContent: 'center', padding: 24, gap: 16 }}>
    <ActivityIndicator /><Button onPress={() => void refreshAccount().catch(report)}>{t("Tentar carregar novamente")}</Button>
  </SafeAreaView>;
  return <OnboardingFlow initialAccount={account} />;
}

function OnboardingFlow({ initialAccount }: { initialAccount: AccountSnapshot }) {
  const c = usePalette();
  const { account, accountBusy, accountCommand, refreshAccount, refresh, completeOnboarding } = useClarify();
  const [step, setStep] = useState<'account' | 'byok' | 'keyboard'>(() =>
    initialAccount.signedIn || initialAccount.pending ? 'account' : initialAccount.hasGroqKey ? 'keyboard' : 'account');
  const [key, setKey] = useState('');
  const [saving, setSaving] = useState(false);
  const [mode, setMode] = useState<'account' | 'byok'>(initialAccount.hosted ? 'account' : 'byok');
  const busy = saving || accountBusy || !!account?.busy;
  const command = (action: string, value = '') => void accountCommand(action, value).catch(report);
  async function continueWithoutAccount() {
    setSaving(true);
    try {
      if (account?.pending) await accountCommand('logout');
      setStep('byok');
    } catch (error) { report(error); }
    finally { setSaving(false); }
  }
  async function prepareKey() {
    setSaving(true);
    try {
      await Core.setKey(key);
      // A user who changed their choice must actually use the key they supplied.
      if (account?.signedIn) await accountCommand('logout');
      await refreshAccount(); await refresh(); setKey(''); setMode('byok'); setStep('keyboard');
    } catch (error) { report(error); }
    finally { setSaving(false); }
  }
  async function finish() {
    setSaving(true);
    try { await completeOnboarding(mode); await refresh(); }
    catch (error) { report(error); }
    finally { setSaving(false); }
  }
  return <SafeAreaView style={{ flex: 1, backgroundColor: c.background }}>
    <ScrollView contentContainerStyle={[ui.content, { flexGrow: 1, justifyContent: 'center', paddingVertical: 32 }]} keyboardShouldPersistTaps="handled" keyboardDismissMode="interactive">
      <View style={{ gap: 20, width: '100%', maxWidth: 520, alignSelf: 'center' }}>
        <ClarifyLogo />
        <Title subtitle={t("Fale. O Clarify transforma sua voz em texto claro.")}>{step === 'byok' ? t("Use sua chave Groq") : step === 'keyboard' ? t("Seu teclado, com Clarify") : account?.signedIn ? t("Sua conta está pronta") : t("Boas-vindas ao Clarify")}</Title>
        {!account ? <ActivityIndicator /> : <Card>
          {step === 'byok' ? <>
            <TextInput accessibilityLabel={t("Chave de API do Groq")} value={key} onChangeText={setKey} editable={!busy} secureTextEntry autoCapitalize="none" autoCorrect={false} placeholder="gsk_…" placeholderTextColor={c.muted} style={[ui.input, { color: c.text, borderColor: c.line }]} />
            <Text style={[ui.small, { color: c.muted }]}>{t("Sua chave fica no Keychain deste iPhone. Áudio, texto e palavras ativas do dicionário são enviados ao serviço escolhido por você. Ao continuar, você autoriza esse processamento.")}</Text>
            <Button loading={saving} disabled={accountBusy || !key.trim()} onPress={() => void prepareKey()}>{t("Salvar chave e continuar")}</Button>
          </> : step === 'keyboard' ? <>
            <Text style={[ui.body, { color: c.text }]}>{t("Para ditar em outros aplicativos, adicione o teclado Clarify:")}</Text>
            <Text style={[ui.body, { color: c.muted }]}>{t("Ajustes → Geral → Teclado → Teclados → Adicionar Novo Teclado → Clarify. Depois, ative “Acesso Total”.")}</Text>
            <Text style={[ui.small, { color: c.muted }]}>{t("No teclado, toque em “Começar” para autorizar o microfone. Você também pode ditar diretamente no Clarify.")}</Text>
            <Button disabled={busy} onPress={() => void Linking.openSettings().catch(report)}>{t("Abrir Ajustes do iPhone")}</Button>
            <Button loading={saving} disabled={accountBusy} onPress={() => void finish()}>{t("Começar a usar")}</Button>
          </> : account.signedIn ? <>
            <Text style={[ui.body, { color: c.text }]}>{account.email}</Text>
            <Text style={[ui.small, { color: c.muted }]}>{t("Para transcrever e reescrever, áudio, texto e palavras ativas do dicionário serão processados pelo Clarify. O histórico fica neste iPhone. A conta inclui até 300 minutos por mês, sujeitos à disponibilidade do beta.")}</Text>
            {!account.hosted ? <Button loading={accountBusy} disabled={busy} onPress={() => command('hosted', '1')}>{t("Ativar processamento do Clarify")}</Button> : <Button disabled={busy} onPress={() => { setMode('account'); setStep('keyboard'); }}>{t("Continuar")}</Button>}
          </> : <>
            <AccountSignIn account={account} busy={busy} command={command} />
          </>}
          {account.error && <Text accessibilityRole="alert" style={[ui.small, { color: c.danger }]}>{t(account.error)}</Text>}
          {step !== 'account' && <TextButton disabled={busy} onPress={() => { setStep('account'); setKey(''); }}>{t("Voltar")}</TextButton>}
        </Card>}
        {step === 'account' && account && !account.signedIn && !account.pending && <TextButton disabled={busy} onPress={() => void continueWithoutAccount()}>{t("Continuar sem conta")}</TextButton>}
      </View>
    </ScrollView>
  </SafeAreaView>;
}
