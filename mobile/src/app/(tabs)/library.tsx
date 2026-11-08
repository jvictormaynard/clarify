import { router } from 'expo-router';
import { ScrollView } from 'react-native';
import { Card, NavigationRow, ScreenHeader, ui, usePalette } from '../../components/ui';
import { ComputerLibraryNotice } from '../../components/computer-connection';
import { useClarify } from '../../state/clarify';
import { t } from '../../i18n';

export default function Library() {
  const c = usePalette();
  const { account } = useClarify();
  return <ScrollView testID="app.library" style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={ui.content} contentInsetAdjustmentBehavior="automatic">
    <ScreenHeader title={t('Biblioteca')} />
    {account?.mode === 'computer' ? <><ComputerLibraryNotice />
      <Card><NavigationRow title={t('Gerenciar conexão')} icon="desktopcomputer" onPress={() => router.push('/processing')} /></Card>
    </> : <Card>
      <NavigationRow testID="library.dictionary" title={t('Dicionário')} icon="book" onPress={() => router.push('/dictionary')} />
      <NavigationRow testID="library.snippets" title={t('Snippets')} icon="text.quote" onPress={() => router.push('/snippets')} />
    </Card>}
  </ScrollView>;
}
