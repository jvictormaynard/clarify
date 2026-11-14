import { FeatureInfo } from '../../components/feature-info';
import { SafeAreaView } from 'react-native-safe-area-context';
import { WorkspaceHeader } from '../../components/workspace-header';
import { usePalette } from '../../components/ui';
import { t } from '../../i18n';
import { NatureCard } from '../../components/nature-card';
import Output from '../output';

export default function Style() {
  const c = usePalette();
  return <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.background }}>
    <WorkspaceHeader title={t('Estilo')} accessory={<FeatureInfo kind="style" />} /><Output close={false} introduction={<NatureCard kind="actions" title={t('Seu texto, do seu jeito.')} detail={t('Escolha a edição, o tom e o idioma dos seus ditados.')} />} />
  </SafeAreaView>;
}
