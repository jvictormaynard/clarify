import { router } from 'expo-router';
import { ScrollView } from 'react-native';
import { QuickStartGuide } from '../components/quick-start-guide';
import { ui, usePalette } from '../components/ui';
import { useClarify } from '../state/clarify';

export default function Guide() {
  const c = usePalette();
  const { account } = useClarify();
  return <ScrollView style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={ui.content}
    contentInsetAdjustmentBehavior="automatic" automaticallyAdjustKeyboardInsets keyboardShouldPersistTaps="handled" keyboardDismissMode="interactive">
    <QuickStartGuide key={`${account?.endpoint}/${account?.email}`} replay onFinish={() => router.back()} />
  </ScrollView>;
}
