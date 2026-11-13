import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { ScrollView, Switch, Text, View } from 'react-native';
import Core from '../../../modules/clarify-core';
import { Section, Divider, NavigationRow, ScreenHeader, ui, usePalette } from '../../components/ui';
import { report, useClarify } from '../../state/clarify';
import { destinationLabel } from '../../processing';
import { TextButton } from '../../components/ui';
import { t } from '../../i18n';

export default function Preferences() {
  const c = usePalette();
  const { account } = useClarify();
  const [autocorrect, setAutocorrect] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);
  useFocusEffect(useCallback(() => {
    let active = true;
    Core.getKeyboardAutocorrectEnabled().then(value => {
      if (active) { setAutocorrect(value); setLoaded(true); }
    }).catch(report);
    return () => { active = false; };
  }, []));
  async function changeAutocorrect(value: boolean) {
    if (saving) return;
    setSaving(true);
    try { await Core.setKeyboardAutocorrectEnabled(value); setAutocorrect(value); }
    catch (error) { report(error); }
    finally { setSaving(false); }
  }
  return <ScrollView testID="app.preferences" style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={ui.content} contentInsetAdjustmentBehavior="automatic">
    <ScreenHeader title={t('Ajustes')} action={<TextButton onPress={() => router.back()}>{t('Fechar')}</TextButton>} />
    <Section title={t('Conta e processamento')}>
      <NavigationRow testID="settings.account" title={t('Conta')} detail={account?.signedIn ? account.email : t('Entrar ou criar conta')} icon="person.crop.circle" onPress={() => router.push('/account')} />
      <Divider />
      <NavigationRow testID="settings.processing" title={t('Processamento')} detail={t(destinationLabel(account))} icon="cpu" onPress={() => router.push('/processing')} />
    </Section>
    <Section title={t('Ditado e teclado')}>
      <NavigationRow testID="settings.output" title={t('Estilo do ditado')} detail={t('Edição, tom e idioma de saída')} icon="textformat" onPress={() => router.push('/output')} />
      <Divider />
      <NavigationRow testID="settings.microphone" title={t('Microfone e teclado')} icon="keyboard" onPress={() => router.push('/microphone')} />
      <Divider />
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12 }}>
        <View style={{ flex: 1, gap: 4 }}>
          <Text style={[ui.body, { color: c.text }]}>{t('Correção automática')}</Text>
          <Text style={[ui.small, { color: c.muted }]}>{t('Mostra sugestões e corrige palavras ao digitar no teclado Clarify.')}</Text>
        </View>
        <Switch testID="settings.autocorrect" accessibilityLabel={t('Correção automática')} value={autocorrect} disabled={!loaded || saving} onValueChange={value => void changeAutocorrect(value)} />
      </View>
    </Section>
    <Section title={t('Privacidade e ajuda')}>
      <NavigationRow testID="settings.privacy" title={t('Histórico e privacidade')} icon="hand.raised" onPress={() => router.push('/privacy')} />
      <Divider />
      <NavigationRow testID="settings.guide" title={t('Como usar')} icon="questionmark.circle" onPress={() => router.push('/guide')} />
    </Section>
  </ScrollView>;
}
