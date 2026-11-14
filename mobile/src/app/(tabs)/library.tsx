import { router } from 'expo-router';
import { ScrollView } from 'react-native';
import { NavigationRow, ScreenHeader, Section, Divider, ui, usePalette } from '../../components/ui';
import { ComputerLibraryNotice } from '../../components/computer-connection';
import { useClarify } from '../../state/clarify';
import { t } from '../../i18n';

export default function Library() {
  const c = usePalette();
  const { account } = useClarify();
  return <ScrollView testID="app.library" style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={ui.content} contentInsetAdjustmentBehavior="automatic">
    <ScreenHeader title={t('Biblioteca')} subtitle={t('Suas palavras, textos e ações.')} />
    {account?.mode === 'computer' ? <>
      <ComputerLibraryNotice />
      <Section title={t('Meu computador')}>
        <NavigationRow title={t('Gerenciar conexão')} icon="desktopcomputer" onPress={() => router.push('/processing')} />
      </Section>
    </> : <Section title={t('Personalizar o Clarify')}>
      <NavigationRow testID="library.dictionary" title={t('Dicionário')} detail={t('Nomes e palavras que você usa.')} icon="book" onPress={() => router.push('/dictionary')} />
      <Divider />
      <NavigationRow testID="library.snippets" title={t('Snippets')} detail={t('Insira textos salvos com uma frase.')} icon="text.quote" onPress={() => router.push('/snippets')} />
    </Section>}
    <Section title={t('Ações de texto')}>
      <NavigationRow testID="library.actions" title={t('Gerenciar ações')} detail={t(account?.mode === 'computer' ? 'Gerencie estas ações no computador pareado.' : 'Crie e edite suas instruções de texto.')}
        icon="wand.and.stars" onPress={() => router.push('/text-actions')} />
    </Section>
  </ScrollView>;
}
