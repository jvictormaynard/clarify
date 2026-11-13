import { useState } from 'react';
import { Pressable, Text } from 'react-native';
import { SymbolView } from 'expo-symbols';
import { t } from '../i18n';
import { useClarify } from '../state/clarify';
import { NativeSheet, ui, usePalette } from './ui';

type FeatureKind = 'dictionary' | 'snippets' | 'style' | 'actions';
const details: Record<FeatureKind, { title: string; paragraphs: string[] }> = {
  dictionary: { title: 'Dicionário', paragraphs: [
    'Adicione nomes e termos que o Clarify deve reconhecer.',
    'As palavras ativas ajudam na transcrição e na reescrita. Elas não são inseridas quando você não as diz. Até 512 palavras.',
  ] },
  snippets: { title: 'Snippets', paragraphs: [
    'Diga uma frase para inserir um texto salvo. Use para assinaturas, endereços e respostas frequentes.',
    'Com a reescrita ativa, o texto do snippet é enviado à IA como parte da mensagem. Quando você diz apenas a frase de ativação, o texto salvo é inserido sem reescrita.',
  ] },
  style: { title: 'Estilo do ditado', paragraphs: [
    'Escolha a edição, o tom e o idioma dos seus ditados.',
    'As alterações valem para a próxima operação.',
  ] },
  actions: { title: 'Ações', paragraphs: [
    'Reescreva ou traduza um texto.',
    'Execute a ação. Revise o resultado e copie quando quiser.',
  ] },
};

export function FeatureInfo({ kind }: { kind: FeatureKind }) {
  const c = usePalette();
  const { account } = useClarify();
  const [open, setOpen] = useState(false);
  const detail = details[kind];
  const computerLibrary = account?.mode === 'computer' && (kind === 'dictionary' || kind === 'snippets');
  return <>
    <Pressable testID={`workspace.info.${kind}`} accessibilityRole="button" accessibilityLabel={t('Como usar')}
      accessibilityState={{ expanded: open }} onPress={() => setOpen(true)}
      style={({ pressed }) => ({ width: 44, height: 44, alignItems: 'center', justifyContent: 'center', opacity: pressed ? 0.6 : 1 })}>
      <SymbolView name="info.circle" size={21} tintColor={c.muted} accessible={false} />
    </Pressable>
    <NativeSheet visible={open} title={t(detail.title)} onClose={() => setOpen(false)}>
      {computerLibrary ? <Text style={[ui.body, { color: c.text }]}>{t('Use o dicionário e os snippets configurados no computador.')}</Text>
        : detail.paragraphs.map(paragraph => <Text key={paragraph} style={[ui.body, { color: c.text }]}>{t(paragraph)}</Text>)}
    </NativeSheet>
  </>;
}
