import { useState } from 'react';
import { ActivityIndicator, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { OnboardingDemo, OnboardingHeader, WelcomeBenefits, PrivacyNote, PrivacyLink, onboardingStyles, OnboardingTitle as Title } from '../components/onboarding-ui';
import { QuickStartGuide } from '../components/quick-start-guide';
import { Button, KeyboardPage, StepContent, TextButton, ui, usePalette } from '../components/ui';
import { t } from '../i18n';
import { isBusy, report, useClarify } from '../state/clarify';

import { ComputerConnectionCard } from '../components/computer-connection';
import { processingAvailable } from '../processing';

export default function Onboarding() {
  const c = usePalette();
  const { account, refreshAccount, markOnboardingPresented, dismissOnboarding, completeOnboarding, accountBusy, computerCommand, state } = useClarify();
  const [started, setStarted] = useState(false);
  const [saving, setSaving] = useState(false);
  const busy = saving || accountBusy || !!account?.busy || isBusy(state);
  const step = !started ? 'welcome' : account?.mode === 'computer' && processingAvailable(account) ? 'guide' : 'account';
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
            <PrivacyNote>{t('setup_mobile_privacy')}</PrivacyNote>
            <View style={onboardingStyles.footer}>
              <PrivacyLink />
              <Button primary testID="onboarding.continue" disabled={busy} onPress={() => { void computerCommand('computer').catch(report); setStarted(true); }}>{`${t('Vamos começar')} →`}</Button>
            </View>
          </View> : !account ? <>
            <ActivityIndicator color={c.text} />
            <Button onPress={() => void refreshAccount().catch(report)}>{t('Tentar carregar novamente')}</Button>
            <TextButton testID="onboarding.skip" onPress={() => void finish()}>{t('Fechar')}</TextButton>
          </> : step === 'guide' ? <QuickStartGuide onBack={() => setStarted(false)} key={`${account.endpoint}/${account.email}`} onFinish={finish} busy={busy} /> : <>
            <OnboardingHeader title={t('Configurar o Clarify')} onBack={() => setStarted(false)} disabled={busy} />
            <Title>{t('setup_phone_title')}</Title>
            <Text style={[ui.body, { color: c.muted }]}>{t('setup_phone_hint')}</Text>
            <ComputerConnectionCard />
            {account.error && <Text accessibilityRole="alert" style={[ui.body, { color: c.text }]}>{t(account.error)}</Text>}
            <TextButton testID="onboarding.skip" disabled={busy} onPress={() => void finish()}>{t('Fechar introdução')}</TextButton>
          </>}
        </StepContent>
      </View>
    </KeyboardPage>
  </SafeAreaView>;
}
