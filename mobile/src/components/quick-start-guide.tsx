import { useState } from 'react';
import { Linking, Text, View } from 'react-native';
import { t } from '../i18n';
import { guideCompletion, guideTransition, initialGuide, practiceResult, type GuideAction, type GuideExit } from '../quick-start';
import { isBusy, report, useClarify } from '../state/clarify';
import { Button, StepContent, TextButton, Title, ui, usePalette } from './ui';

export function QuickStartGuide({ onFinish, busy = false, replay = false }: {
  onFinish: (confirmed: boolean) => Promise<void> | void; busy?: boolean; replay?: boolean;
}) {
  const c = usePalette();
  const { state, activate, activating } = useClarify();
  const [progress, setProgress] = useState(initialGuide);
  const [previousOperation, setPreviousOperation] = useState<string | undefined>();
  const [finishing, setFinishing] = useState(false);
  const blocked = busy || finishing || activating || isBusy(state);
  const step = progress.step === 'keyboard' ? 0 : progress.step === 'microphone' ? 1 : 2;
  const result = step === 2 ? practiceResult(state, previousOperation) : null;
  function move(action: GuideAction) {
    if (action === 'continue-microphone' && state.sessionActive) setPreviousOperation(state.operationID);
    setProgress(current => guideTransition(current, action, state.sessionActive));
  }
  async function finish(exit: GuideExit) {
    if (blocked) return;
    const confirmed = guideCompletion(progress, exit);
    if (confirmed === null) return;
    setFinishing(true);
    try { await onFinish(confirmed); }
    catch (error) { report(error); }
    finally { setFinishing(false); }
  }
  return <View testID={`onboarding.${progress.step}`} collapsable={false} style={{ gap: 24 }}>
    <View accessibilityRole="progressbar" accessibilityLabel={t('Como usar')} accessibilityValue={{ min: 1, max: 3, now: step + 1 }}
      style={{ flexDirection: 'row', gap: 8 }}>
      {[0, 1, 2].map(index => <View key={index} style={{ flex: 1, height: 3, borderRadius: 2, backgroundColor: index <= step ? c.text : c.line }} />)}
    </View>
    <StepContent step={progress.step}>
      {progress.step === 'keyboard' ? <>
        <Title>{t('Adicione o teclado Clarify')}</Title>
        <Text style={[ui.body, { color: c.text }]}>{t('1. Abra Ajustes → Geral → Teclado → Teclados.')}</Text>
        <Text style={[ui.body, { color: c.text }]}>{t('2. Toque em Adicionar Novo Teclado e escolha Clarify.')}</Text>
        <Text style={[ui.body, { color: c.text }]}>{t('3. Abra Clarify nessa lista e ative Acesso Total.')}</Text>
        <Button testID="onboarding.openSettings" disabled={blocked} onPress={() => void Linking.openSettings().catch(report)}>{t('Abrir Ajustes do iPhone')}</Button>
        <Button primary testID="onboarding.continue" disabled={blocked} onPress={() => move('confirm-keyboard')}>{t('Já configurei o teclado')}</Button>
      </> : progress.step === 'microphone' ? <>
        <Title subtitle={t('O microfone fica disponível entre os ditados do teclado.')}>{t('Ative o microfone')}</Title>
        <Text accessibilityLiveRegion="polite" style={[ui.body, { color: c.muted }]}>{state.sessionActive ? t('Microfone ativo') : t('Microfone desativado')}</Text>
        {state.message && <Text accessibilityRole="alert" style={[ui.body, { color: c.text }]}>{t(state.message)}</Text>}
        {state.sessionActive ? <Button primary testID="onboarding.continue" disabled={blocked} onPress={() => move('continue-microphone')}>{t('Continuar')}</Button>
          : <Button primary testID="onboarding.activateMicrophone" loading={activating} disabled={blocked} onPress={() => void activate().catch(report)}>{t('Ativar microfone')}</Button>}
        {!!state.message && !state.sessionActive && <TextButton disabled={blocked} onPress={() => void Linking.openSettings().catch(report)}>{t('Abrir Ajustes do iPhone')}</TextButton>}
      </> : <>
        <Title>{t('Experimente um ditado')}</Title>
        <Text style={[ui.body, { color: c.text }]}>{t('Abra uma nota e escolha o teclado Clarify pelo globo.')}</Text>
        <Text style={[ui.body, { color: c.text }]}>{t('Toque no microfone, fale e toque em concluir.')}</Text>
        <Text style={[ui.section, { color: c.text, marginTop: 0, paddingVertical: 8 }]}>{t('Oi, tudo bem?')}</Text>
        <Text style={[ui.small, { color: c.muted }]}>{t('Use uma nota ou mensagem de teste, sem enviar.')}</Text>
        {result && <Text selectable style={[ui.body, { color: c.text }]}>{result}</Text>}
        {state.message && <Text accessibilityRole="alert" style={[ui.body, { color: c.text }]}>{t(state.message)}</Text>}
        <Button primary testID="onboarding.continue" loading={finishing} disabled={blocked} onPress={() => void finish('confirmed')}>{t('O texto apareceu')}</Button>
        {!replay && <TextButton testID="onboarding.openHome" disabled={blocked} onPress={() => void finish('home')}>{t('Abrir Início para testar')}</TextButton>}
      </>}
    </StepContent>
    <View style={[ui.row, { paddingTop: 8 }]}>
      {progress.step !== 'keyboard' ? <TextButton testID="onboarding.back" disabled={blocked} onPress={() => move('back')}>{t('Voltar')}</TextButton> : <View />}
      <TextButton testID="onboarding.skip" disabled={blocked} onPress={() => void finish('later')}>{replay ? t('Fechar') : t('Fazer depois')}</TextButton>
    </View>
  </View>;
}
