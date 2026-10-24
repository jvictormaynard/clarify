import { t } from "../i18n";
import { router } from 'expo-router';
import { ScrollView, View } from 'react-native';
import { AccountCard } from '../components/account-card';
import { Card, NavigationRow, ui, usePalette } from '../components/ui';

export default function Account() {
  const c = usePalette();
  return <ScrollView style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={ui.content} contentInsetAdjustmentBehavior="automatic" keyboardShouldPersistTaps="handled">
    <AccountCard>
      <Card>
        <NavigationRow testID="account.settings" title={t('Ajustes')} detail={t('Microfone, teclado e dados.')} icon="slider.horizontal.3" onPress={() => router.push('/settings')} />
        <View style={{ height: 1, backgroundColor: c.line }} />
        <NavigationRow testID="account.guide" title={t('Como usar')} detail={t('Reveja a configuração e teste um ditado.')} icon="questionmark.circle" onPress={() => router.push('/guide')} />
      </Card>
    </AccountCard>
  </ScrollView>;
}
