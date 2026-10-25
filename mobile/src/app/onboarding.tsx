import { useState } from 'react';
import { ActivityIndicator, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { AccountSignIn } from '../components/account-sign-in';
import { ClarifyLogo } from '../components/clarify-logo';
import { QuickStartGuide } from '../components/quick-start-guide';
import { Button, KeyboardPage, StepContent, TextButton, Title, ui, usePalette } from '../components/ui';
import { t } from '../i18n';
import { isBusy, report, useClarify } from '../state/clarify';

export default function Onboarding() {
  const c = usePalette();
  const { account, refreshAccount, markOnboardingPresented, dismissOnboarding, completeOnboarding, accountBusy, accountCommand, state } = useClarify();
  const [started, setStarted] = useState(false);
  const [saving, setSaving] = useState(false);
  const busy = saving || accountBusy || !!account?.busy || isBusy(state);
  const step = !started ? 'welcome' : account?.signedIn ? 'guide' : 'account';
  async function finish(confirmed = false) {
    if (busy) return;
    setSaving(true);
    try { if (confirmed) await completeOnboarding(); else await dismissOnboarding(); }
    catch (error) { report(error); }
    finally { setSaving(false); }
  }
  return <SafeAreaView style={{ flex: 1, backgroundColor: c.background }}>
    <KeyboardPage contentContainerStyle={{ justifyContent: 'center', paddingVertical: 32 }}>
      <View onLayout={() => void markOnboardingPresented().catch(report)} style={{ width: '100%' }}>
        <StepContent step={step}>
          {step === 'welcome' ? <View testID="onboarding.welcome" collapsable={false} style={{ gap: 28 }}>
            <ClarifyLogo size={48} />
            <Title subtitle={t('Use sua voz para escrever em outros aplicativos.')}>{t('Fale. O Clarify escreve.')}</Title>
            <Button primary testID="onboarding.continue" disabled={busy} onPress={() => setStarted(true)}>{t('Começar')}</Button>
            <TextButton testID="onboarding.skip" disabled={busy} onPress={() => void finish()}>{t('Agora não')}</TextButton>
          </View> : !account ? <>
            <ActivityIndicator color={c.text} />
            <Button onPress={() => void refreshAccount().catch(report)}>{t('Tentar carregar novamente')}</Button>
            <TextButton testID="onboarding.skip" onPress={() => void finish()}>{t('Fechar')}</TextButton>
          </> : step === 'guide' ? <QuickStartGuide key={`${account.endpoint}/${account.email}`} onFinish={finish} busy={busy} /> : <>
            <Title>{t('Entre no Clarify')}</Title>
            <Text style={[ui.body, { color: c.muted }]}>{t('Para transcrever e reescrever, o Clarify processa áudio, texto e palavras ativas do dicionário. O histórico da conta é sincronizado entre seus dispositivos. Patrocínios financiam uma cota semanal individual. Novas contas podem receber uma cota inicial proporcional ao tempo até a renovação. Sem saldo de patrocínio, a conta aguarda a próxima distribuição.')}</Text>
            <AccountSignIn account={account} busy={busy} command={accountCommand} />
            {account.error && <Text accessibilityRole="alert" style={[ui.body, { color: c.text }]}>{t(account.error)}</Text>}
            <TextButton testID="onboarding.skip" disabled={busy} onPress={() => void finish()}>{t('Fechar introdução')}</TextButton>
          </>}
        </StepContent>
      </View>
    </KeyboardPage>
  </SafeAreaView>;
}
