import { ScrollView } from 'react-native';
import { AccountCard } from '../components/account-card';
import { ui, usePalette } from '../components/ui';

export default function Account() {
  const c = usePalette();
  return <ScrollView automaticallyAdjustKeyboardInsets keyboardDismissMode="interactive" testID="app.account" style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={ui.content} contentInsetAdjustmentBehavior="automatic" keyboardShouldPersistTaps="handled">
    <AccountCard />
  </ScrollView>;
}
