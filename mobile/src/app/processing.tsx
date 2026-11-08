import { ScrollView } from 'react-native';
import { router } from 'expo-router';
import { ProcessingChoice, ComputerConnectionCard } from '../components/computer-connection';
import { Card, NavigationRow, ui, usePalette } from '../components/ui';
import { useClarify } from '../state/clarify';
import { t } from '../i18n';

export default function Processing() {
  const c = usePalette();
  const { account } = useClarify();
  return <ScrollView testID="app.processing" style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={ui.content} contentInsetAdjustmentBehavior="automatic">
    <ProcessingChoice />
    {account?.mode === 'computer' ? <ComputerConnectionCard /> : <Card>
      <NavigationRow title={t('Conta Clarify')} detail={account?.signedIn ? account.email : t('Entrar ou criar conta')} icon="person.crop.circle" onPress={() => router.push('/account')} />
    </Card>}
  </ScrollView>;
}
