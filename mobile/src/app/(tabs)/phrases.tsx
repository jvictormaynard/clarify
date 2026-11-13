import { FeatureInfo } from '../../components/feature-info';
import { SafeAreaView } from 'react-native-safe-area-context';
import { WorkspaceHeader } from '../../components/workspace-header';
import { usePalette } from '../../components/ui';
import { t } from '../../i18n';
import Snippets from '../snippets';

export default function Page() {
  const c = usePalette();
  return <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.background }}>
    <WorkspaceHeader title={t('Snippets')} accessory={<FeatureInfo kind="snippets" />} /><Snippets />
  </SafeAreaView>;
}
