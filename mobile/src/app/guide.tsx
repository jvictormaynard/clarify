import { router } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { QuickStartGuide } from '../components/quick-start-guide';
import { KeyboardPage, usePalette } from '../components/ui';
import { useClarify } from '../state/clarify';

export default function Guide() {
  const c = usePalette();
  const { account } = useClarify();
  return <SafeAreaView style={{ flex: 1, backgroundColor: c.background }}>
    <KeyboardPage contentContainerStyle={{ paddingTop: 8 }}>
      <QuickStartGuide key={`${account?.endpoint}/${account?.email}`} replay onFinish={() => router.back()} />
    </KeyboardPage>
  </SafeAreaView>;
}
