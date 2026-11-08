import { SafeAreaView } from 'react-native-safe-area-context';
import { SnippetsLibrary } from '../components/snippets-library';
import { usePalette } from '../components/ui';
import { useClarify } from '../state/clarify';

export default function Snippets() {
  const c = usePalette();
  const { account } = useClarify();
  const scope = account?.historyContext ?? 'guest';
  return <SafeAreaView edges={[]} style={{ flex: 1, backgroundColor: c.background }}>
    <SnippetsLibrary key={scope} />
  </SafeAreaView>;
}
