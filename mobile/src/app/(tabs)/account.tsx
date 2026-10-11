import { router } from 'expo-router';
import { ScrollView, View } from 'react-native';
import { AccountCard } from '../../components/account-card';
import { TextButton, Title, ui, usePalette } from '../../components/ui';

export default function Account() {
  const c = usePalette();
  return <ScrollView style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={ui.content} contentInsetAdjustmentBehavior="automatic" keyboardShouldPersistTaps="handled">
    <View style={ui.row}><Title>Conta</Title><TextButton onPress={() => router.push('/settings')}>Ajustes</TextButton></View>
    <AccountCard />
  </ScrollView>;
}
