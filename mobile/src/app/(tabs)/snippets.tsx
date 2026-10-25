import { SafeAreaView } from 'react-native-safe-area-context';
import { SnippetsLibrary } from '../../components/snippets-library';
import { usePalette } from '../../components/ui';
import { useClarify } from '../../state/clarify';

export default function Snippets() {
  const c = usePalette();
  const { account } = useClarify();
  const scope = account?.signedIn ? `${account.endpoint}/${account.email}` : 'guest';
  return <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.background }}>
    <SnippetsLibrary key={scope} />
  </SafeAreaView>;
}
