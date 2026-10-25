import { t } from "../i18n";
import { useState } from 'react';
import { ActivityIndicator, Linking, ScrollView, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
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
  return <OnboardingFlow />;
}

function OnboardingFlow() {
  const c = usePalette();
  const { account, accountBusy, accountCommand, refresh, completeOnboarding } = useClarify();
  const [step, setStep] = useState<'account' | 'keyboard'>('account');
  const [saving, setSaving] = useState(false);
  const showKeyboard = step === 'keyboard' && account?.signedIn;
  const busy = saving || accountBusy || !!account?.busy;
  async function finish() {
    setSaving(true);
    try { await completeOnboarding(); await refresh(); }
    catch (error) { report(error); }
    finally { setSaving(false); }
  }
  return <SafeAreaView style={{ flex: 1, backgroundColor: c.background }}>
    <ScrollView contentContainerStyle={[ui.content, { flexGrow: 1, justifyContent: 'center', paddingVertical: 32 }]} keyboardShouldPersistTaps="handled" keyboardDismissMode="interactive">
      <View style={{ gap: 20, width: '100%', maxWidth: 520, alignSelf: 'center' }}>
        <ClarifyLogo />
        <Title subtitle={t("Fale. O Clarify transforma sua voz em texto claro.")}>{showKeyboard ? t("Seu teclado, com Clarify") : account?.signedIn ? t("Sua conta está pronta") : t("Boas-vindas ao Clarify")}</Title>
        {!account ? <ActivityIndicator /> : <Card>
          {showKeyboard ? <>
            <Text style={[ui.body, { color: c.text }]}>{t("Para ditar em outros aplicativos, adicione o teclado Clarify:")}</Text>
            <Text style={[ui.body, { color: c.muted }]}>{t("Ajustes → Geral → Teclado → Teclados → Adicionar Novo Teclado → Clarify. Depois, ative “Acesso Total”.")}</Text>
            <Text style={[ui.small, { color: c.muted }]}>{t("No teclado, toque em “Começar” para autorizar o microfone. Você também pode ditar diretamente no Clarify.")}</Text>
            <Button disabled={busy} onPress={() => void Linking.openSettings().catch(report)}>{t("Abrir Ajustes do iPhone")}</Button>
            <Button loading={saving} disabled={accountBusy} onPress={() => void finish()}>{t("Começar a usar")}</Button>
          </> : account.signedIn ? <>
            <Text style={[ui.body, { color: c.text }]}>{account.email}</Text>
            <Text style={[ui.small, { color: c.muted }]}>{t("Para transcrever e reescrever, áudio, texto e palavras ativas do dicionário serão processados pelo Clarify. O histórico fica neste iPhone. A conta inclui até 300 minutos por mês, sujeitos à disponibilidade do beta.")}</Text>
            <Button disabled={busy} onPress={() => setStep('keyboard')}>{t("Continuar")}</Button>
          </> : <>
            <Text style={[ui.small, { color: c.muted }]}>{t("Entre para ditar sem chave de API e compartilhar seu dicionário com o computador.")}</Text>
            <AccountSignIn account={account} busy={busy} command={accountCommand} />
          </>}
          {account.error && <Text accessibilityRole="alert" style={[ui.small, { color: c.danger }]}>{t(account.error)}</Text>}
          {showKeyboard && <TextButton disabled={busy} onPress={() => setStep('account')}>{t("Voltar")}</TextButton>}
        </Card>}
      </View>
    </ScrollView>
  </SafeAreaView>;
}
