import { useRef, useState } from 'react';
import { Keyboard, Linking, Text, View, type TextInput } from 'react-native';
import { SymbolView } from 'expo-symbols';
import { OnboardingHeader, KeyboardSetupIllustration, PrivacyNote, onboardingStyles, OnboardingTitle as Title } from './onboarding-ui';
import { DraftTextInput } from './draft-text-input';
import { t } from '../i18n';
import { guideCompletion, guideTransition, initialGuide, type GuideAction, type GuideExit } from '../quick-start';
import { isBusy, report, useClarify } from '../state/clarify';
import { Button, StepContent, TextButton, ui, usePalette } from './ui';

export function QuickStartGuide({ onFinish, busy = false, replay = false, onBack }: {
  onFinish: (confirmed: boolean) => Promise<void> | void; busy?: boolean; replay?: boolean; onBack?: () => void;
}) {
  const c = usePalette();
  const { state, activate, activating } = useClarify();
  const [progress, setProgress] = useState(initialGuide);
  const [practiceText, setPracticeText] = useState('');
  const [practiceFocused, setPracticeFocused] = useState(false);
  const practiceInput = useRef<TextInput>(null);
  const [finishing, setFinishing] = useState(false);
  const blocked = busy || finishing || activating || isBusy(state);
  function move(action: GuideAction) {
    practiceInput.current?.clear();
    setPracticeText('');
    setPracticeFocused(false);
    Keyboard.dismiss();
    setProgress(current => guideTransition(current, action, state.sessionActive));
  }
  async function finish(exit: GuideExit) {
    if (blocked) return;
    const confirmed = guideCompletion(progress, exit, practiceText);
    if (confirmed === null) return;
    setFinishing(true);
    try {
      await onFinish(confirmed);
      practiceInput.current?.clear();
      setPracticeText('');
      Keyboard.dismiss();
    }
    catch (error) { report(error); }
    finally { setFinishing(false); }
  }
  return <View testID={`onboarding.${progress.step}`} collapsable={false} style={{ flexGrow: 1, gap: 24 }}>
    <OnboardingHeader testID="onboarding.back" title={t('Configurar o Clarify')} disabled={blocked}
      onBack={() => { if (progress.step === 'keyboard') { if (onBack) onBack(); else void finish('later'); } else move('back'); }} />
    <StepContent step={progress.step} style={{ flexGrow: 1 }}>
      {progress.step === 'keyboard' ? <>
        <Title subtitle={t('Siga estes passos para ditar em qualquer aplicativo.')}>{t('Vamos começar')}</Title>
        <KeyboardSetupIllustration />
        <PrivacyNote>{t('O Acesso Total permite que o teclado envie seu ditado ao aplicativo Clarify. Áudio e texto são processados na sua conta ou no computador conectado, conforme sua escolha.')}</PrivacyNote>
        <View style={onboardingStyles.footer}>
          <Button primary testID="onboarding.openSettings" disabled={blocked} onPress={() => void Linking.openSettings().catch(report)}>{t('Abrir Ajustes')}</Button>
          <TextButton testID="onboarding.continue" disabled={blocked} onPress={() => move('confirm-keyboard')}>{t('Já configurei o teclado')}</TextButton>
        </View>
      </> : progress.step === 'microphone' ? <>
        <Title subtitle={t('O microfone fica disponível entre os ditados do teclado.')}>{t('Ative o microfone')}</Title>
        <PrivacyNote>{t('Permita o acesso ao microfone para ditar. Você pode desativá-lo depois no Clarify.')}</PrivacyNote>
        <Text accessibilityLiveRegion="polite" style={[ui.body, { color: c.muted }]}>{state.sessionActive ? t('Microfone ativo') : t('Microfone desativado')}</Text>
        {state.message && <Text accessibilityRole="alert" style={[ui.body, { color: c.danger }]}>{t(state.message)}</Text>}
        <View style={onboardingStyles.footer}>
          {state.sessionActive ? <Button primary testID="onboarding.continue" disabled={blocked} onPress={() => move('continue-microphone')}>{t('Continuar')}</Button>
            : <Button primary testID="onboarding.activateMicrophone" loading={activating} disabled={blocked} onPress={() => void activate().catch(report)}>{t('Ativar microfone')}</Button>}
          {!!state.message && !state.sessionActive && <TextButton disabled={blocked} onPress={() => void Linking.openSettings().catch(report)}>{t('Abrir Ajustes do iPhone')}</TextButton>}
        </View>
      </> : <>
        <View style={{ alignItems: 'center', gap: 20, paddingTop: 12 }}>
          <View style={{ width: 52, height: 52, borderRadius: 26, backgroundColor: c.accent, alignItems: 'center', justifyContent: 'center' }}>
            <SymbolView name="checkmark" size={24} tintColor={c.background} accessible={false} />
          </View>
          <Text accessibilityRole="header" style={[ui.title, { fontSize: 32, lineHeight: 40, textAlign: 'center', color: c.text }]}>{t('Tudo pronto!')}</Text>
          <Text style={[ui.body, { textAlign: 'center', color: c.muted }]}>{t('Toque no microfone para falar. Toque em enviar para concluir.')}</Text>
        </View>
        <DraftTextInput inputRef={practiceInput} testID="onboarding.practiceInput" accessibilityLabel={t('Texto de teste')}
          initialValue={practiceText} onChangeText={setPracticeText} editable={!finishing} autoFocus multiline
          onFocus={() => setPracticeFocused(true)} onBlur={() => setPracticeFocused(false)}
          placeholder={t('Experimente: sexta às 14h funciona para você?')} placeholderTextColor={c.muted} selectionColor={c.accent}
          style={[ui.input, { color: c.text, borderColor: practiceFocused ? c.text : c.controlBorder, backgroundColor: c.card, maxHeight: 140, textAlignVertical: 'top' }]} />
        <Text style={[ui.small, { color: c.muted }]}>{t('Toque no campo e escolha o teclado Clarify pelo globo.')}</Text>
        {state.message && <Text accessibilityRole="alert" style={[ui.body, { color: c.danger }]}>{t(state.message)}</Text>}
        <View style={onboardingStyles.footer}>
          <Button primary testID="onboarding.continue" loading={finishing} disabled={blocked || guideCompletion(progress, 'confirmed', practiceText) !== true}
            onPress={() => void finish('confirmed')}>{t('Concluir')}</Button>
        </View>
      </>}
    </StepContent>
    <TextButton testID="onboarding.skip" disabled={blocked} onPress={() => void finish('later')}>{replay ? t('Fechar') : t('Fazer depois')}</TextButton>
  </View>;
}
