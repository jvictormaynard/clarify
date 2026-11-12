import { useState } from 'react';
import { ActivityIndicator, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { AccountSignIn } from '../components/account-sign-in';
import { OnboardingDemo, OnboardingHeader, WelcomeBenefits, PrivacyNote, PrivacyLink, onboardingStyles, OnboardingTitle as Title } from '../components/onboarding-ui';
import { QuickStartGuide } from '../components/quick-start-guide';
import { Button, KeyboardPage, StepContent, TextButton, ui, usePalette } from '../components/ui';
import { t } from '../i18n';
import { isBusy, report, useClarify } from '../state/clarify';

import { ProcessingChoice, ComputerConnectionCard } from '../components/computer-connection';
import { processingAvailable } from '../processing';

export default function Onboarding() {
  const c = usePalette();
  const { account, refreshAccount, markOnboardingPresented, dismissOnboarding, completeOnboarding, accountBusy, accountCommand, state } = useClarify();
  const [started, setStarted] = useState(false);
  const [saving, setSaving] = useState(false);
  const busy = saving || accountBusy || !!account?.busy || isBusy(state);
  const step = !started ? 'welcome' : processingAvailable(account) ? 'guide' : 'account';
  async function finish(confirmed = false) {
    if (busy) return;
    setSaving(true);
    try { if (confirmed) await completeOnboarding(); else await dismissOnboarding(); }
    catch (error) { report(error); }
    finally { setSaving(false); }
  }
  return <SafeAreaView style={{ flex: 1, backgroundColor: c.background }}>
    <KeyboardPage contentContainerStyle={{ paddingTop: 8, gap: 0 }}>
      <View onLayout={() => void markOnboardingPresented().catch(report)} style={{ width: '100%', flexGrow: 1 }}>
        <StepContent step={step} style={{ flexGrow: 1 }}>
          {step === 'welcome' ? <View testID="onboarding.welcome" collapsable={false} style={{ flexGrow: 1, gap: 16 }}>
            <OnboardingHeader testID="onboarding.skip" title="Clarify" onBack={() => void finish()} disabled={busy} />
            <View style={{ marginHorizontal: -20 }}><OnboardingDemo /></View>
            <Title subtitle={t('Diga o que precisa. O Clarify cuida do texto.')}>{t('Boas-vindas ao Clarify')}</Title>
            <WelcomeBenefits />
            <PrivacyNote>{t('O áudio e o texto são processados no destino que você escolher. O histórico da conta é sincronizado entre seus dispositivos.')}</PrivacyNote>
            <View style={onboardingStyles.footer}>
              <PrivacyLink />
              <Button primary testID="onboarding.continue" disabled={busy} onPress={() => setStarted(true)}>{`${t('Vamos começar')} →`}</Button>
            </View>
          </View> : !account ? <>
            <ActivityIndicator color={c.text} />
            <Button onPress={() => void refreshAccount().catch(report)}>{t('Tentar carregar novamente')}</Button>
            <TextButton testID="onboarding.skip" onPress={() => void finish()}>{t('Fechar')}</TextButton>
          </> : step === 'guide' ? <QuickStartGuide onBack={() => setStarted(false)} key={`${account.endpoint}/${account.email}`} onFinish={finish} busy={busy} /> : <>
            <OnboardingHeader title={t('Configurar o Clarify')} onBack={() => setStarted(false)} disabled={busy} />
            <Title>{t('Escolha como usar o Clarify')}</Title>
            <ProcessingChoice />
            {account.mode === 'computer' ? <ComputerConnectionCard /> : <>
              <Text style={[ui.body, { color: c.muted }]}>{t('Para transcrever e reescrever, o Clarify processa áudio, texto e palavras ativas do dicionário. O histórico da conta é sincronizado entre seus dispositivos. Patrocínios financiam uma cota semanal individual. Novas contas podem receber uma cota inicial proporcional ao tempo até a renovação. Sem saldo de patrocínio, a conta aguarda a próxima distribuição.')}</Text>
              <AccountSignIn account={account} busy={busy} command={accountCommand} />
            </>}
            {account.error && <Text accessibilityRole="alert" style={[ui.body, { color: c.text }]}>{t(account.error)}</Text>}
            <TextButton testID="onboarding.skip" disabled={busy} onPress={() => void finish()}>{t('Fechar introdução')}</TextButton>
          </>}
        </StepContent>
      </View>
    </KeyboardPage>
  </SafeAreaView>;
}
