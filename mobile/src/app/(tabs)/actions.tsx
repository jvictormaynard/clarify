import { FeatureInfo } from '../../components/feature-info';
import { SafeAreaView } from 'react-native-safe-area-context';
import { KeyboardPage, usePalette } from '../../components/ui';
import { WorkspaceHeader } from '../../components/workspace-header';
import { ComputerText } from '../../components/computer-text';
import { t } from '../../i18n';

export default function Actions() {
  const c = usePalette();
  return <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.background }}>
    <WorkspaceHeader title={t('Ações')} accessory={<FeatureInfo kind="actions" />} /><KeyboardPage><ComputerText /></KeyboardPage>
  </SafeAreaView>;
}
