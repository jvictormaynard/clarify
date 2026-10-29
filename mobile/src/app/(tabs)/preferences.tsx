import { router } from 'expo-router';
import { ScrollView } from 'react-native';
import { Card, NavigationRow, ScreenHeader, ui, usePalette } from '../../components/ui';
import { useClarify } from '../../state/clarify';
import { destinationLabel } from '../../processing';
import { t } from '../../i18n';

export default function Preferences() {
  const c = usePalette();
  const { account } = useClarify();
  return <ScrollView testID="app.preferences" style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={ui.content} contentInsetAdjustmentBehavior="automatic">
    <ScreenHeader title={t('Ajustes')} />
    <Card>
      <NavigationRow testID="settings.processing" title={t('Processamento')} detail={t(destinationLabel(account))} icon="cpu" onPress={() => router.push('/processing')} />
      <NavigationRow testID="settings.account" title={t('Conta')} detail={account?.signedIn ? account.email : t('Entrar ou criar conta')} icon="person.crop.circle" onPress={() => router.push('/account')} />
      <NavigationRow testID="settings.output" title={t('Saída do ditado')} icon="textformat" onPress={() => router.push('/output')} />
    </Card>
    <Card>
      <NavigationRow testID="settings.microphone" title={t('Microfone e teclado')} icon="keyboard" onPress={() => router.push('/microphone')} />
      <NavigationRow testID="settings.privacy" title={t('Histórico e privacidade')} icon="hand.raised" onPress={() => router.push('/privacy')} />
      <NavigationRow testID="settings.guide" title={t('Como usar')} icon="questionmark.circle" onPress={() => router.push('/guide')} />
    </Card>
  </ScrollView>;
}
