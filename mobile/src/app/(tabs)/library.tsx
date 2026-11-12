import { router } from 'expo-router';
import { ScrollView, Text, View } from 'react-native';
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
    </> : <>
      <LibraryCard kind="dictionary" />
      <LibraryCard kind="snippets" />
    </>}

  </ScrollView>;
}

// Illustrative content uses the same input/result construction as desktop guides.
function LibraryCard({ kind }: { kind: 'dictionary' | 'snippets' }) {
  const c = usePalette();
  const dictionary = kind === 'dictionary';
  return <Card style={{ padding: 0, overflow: 'hidden' }}>
    <View accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
      style={{ backgroundColor: c.accentSoft, padding: 24, gap: 12 }}>
      <View style={{ borderRadius: 8, padding: 12, gap: 4, backgroundColor: c.card, borderWidth: 1, borderColor: c.line }}>
        <Text style={[ui.small, { color: c.muted }]}>{t(dictionary ? 'Palavra' : 'Frase de ativação')}</Text>
        <Text style={[ui.body, { color: c.text }]}>{dictionary ? 'Clarify' : t('minha assinatura')}</Text>
      </View>
      <View style={{ borderLeftWidth: 2, borderLeftColor: c.controlBorder, paddingLeft: 12, gap: 4 }}>
        <Text style={[ui.small, { color: c.muted }]}>{t(dictionary ? 'Pronúncia' : 'Texto a inserir')}</Text>
        <Text style={[ui.body, { color: c.text }]}>{dictionary ? 'clarifai' : t('Atenciosamente,\nAlex')}</Text>
      </View>
    </View>
    <View style={{ paddingHorizontal: 16, paddingBottom: 12 }}>
      <NavigationRow testID={`library.${kind}`} title={t(dictionary ? 'Dicionário' : 'Snippets')}
        icon={dictionary ? 'book' : 'text.quote'} onPress={() => router.push(dictionary ? '/dictionary' : '/snippets')} />
    </View>
  </Card>;
}
