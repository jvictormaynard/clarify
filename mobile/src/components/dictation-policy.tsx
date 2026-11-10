import { useCallback, useRef, useState } from 'react';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Text } from 'react-native';
import Core, { type DictationPolicy, type OutputLanguage } from '../../modules/clarify-core';
import { TextButton, ChoiceRow, Section, ui, usePalette } from './ui';
import { useClarify } from '../state/clarify';
import { errorMessage } from '../errors';
import { t } from '../i18n';
import { dictationPolicyOptions } from '../dictation-policy';

export function DictationPolicyControls({ outputLanguage, tone, more, localTone = false }: { outputLanguage?: OutputLanguage; tone?: React.ReactNode; more?: React.ReactNode; localTone?: boolean }) {
  const c = usePalette();
  const { account } = useClarify();
  const context = account?.historyContext ?? '';
  const catalog = account?.mode === 'computer' ? account.computer : account;
  const [policy, setPolicy] = useState<DictationPolicy>();
  const [choosing, setChoosing] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const saving = useRef(false);
  const generation = useRef(0);
  useFocusEffect(useCallback(() => {
    if (!context) return;
    const request = ++generation.current;
    setPolicy(undefined); setChoosing(false); setError('');
    void Core.getDictationPolicy().then(value => { if (request === generation.current) setPolicy(value); })
      .catch(error => { if (request === generation.current) setError(errorMessage(error)); });
    return () => { ++generation.current; };
  }, [context]));
  async function save(mode: DictationPolicy['mode'], actionID = '', revision = '', language: DictationPolicy['language'] = 'auto') {
    if (saving.current || !context) return;
    saving.current = true; setPending(true); setError('');
    const request = generation.current;
    try {
      const value = await Core.setDictationPolicy(mode, actionID, revision, language, context);
      if (request === generation.current) { setPolicy(value); setChoosing(false); }
    } catch (error) { if (request === generation.current) setError(errorMessage(error)); }
    finally { saving.current = false; setPending(false); }
  }
  const options = dictationPolicyOptions(policy, catalog, account?.mode === 'computer', outputLanguage);
  return <>
    <Section title={t('Edição do texto')}>
      {options.modes.map(mode => <ChoiceRow key={mode.value} testID={`output.policy.${mode.value}`} title={t(mode.label)}
        selected={policy?.mode === mode.value} disabled={!policy || pending || !mode.supported}
        onPress={() => void save(mode.value)} />)}
      {options.compatibilityLabel && <ChoiceRow testID="output.policy.compatibility" title={t(options.compatibilityLabel)} selected disabled onPress={() => {}} />}
    </Section>
    {(options.toneAllowed || (localTone && policy && ['legacy', 'natural', 'clarity'].includes(policy.mode))) && tone}
    <TextButton testID="output.more" expanded={expanded} onPress={() => setExpanded(!expanded)}>{t('Mais opções')}</TextButton>
    {expanded && <Section title={t('Mais opções')}>
    <Text style={[ui.small, { color: c.muted }]}>{t('Idioma e tom se aplicam à revisão e às ações de texto.')}</Text>
    {more}
    <ChoiceRow testID="output.policy.action" title={t('Aplicar ação de texto')}
      selected={choosing || policy?.mode === 'action'} disabled={!policy || pending || !options.actionsSupported}
      onPress={() => setChoosing(true)} />
    {(choosing || policy?.mode === 'action') && <>
      <ChoiceRow testID="output.policy.action.off" title={t('Não aplicar ação automaticamente')}
        selected={policy?.mode !== 'action'} disabled={!policy || pending || !options.modes.find(mode => mode.value === 'clarity')?.supported}
        onPress={() => { if (policy?.mode === 'action') void save('clarity'); else setChoosing(false); }} />
      {options.actions.map(action => <ChoiceRow key={action.id} testID={`output.policy.action.${action.id}`}
        title={action.name} selected={policy?.actionID === action.id}
        disabled={pending || !action.selectable}
        onPress={() => void save('action', action.id, action.revision, outputLanguage ?? 'auto')} />)}
      {policy?.mode === 'action' && !options.selected && <Text accessibilityRole="alert" style={[ui.small, { color: c.danger }]}>{t('A ação mudou. Atualize as ações.')}</Text>}
      <Text style={[ui.small, { color: c.muted }]}>{t('Escolha uma ação para salvar. Até lá, a configuração anterior continua ativa.')}</Text>
      <Text style={[ui.small, { color: c.muted }]}>{t('A tradução usa o idioma de saída acima. Selecione um idioma antes de escolher a ação.')}</Text>
    </>}
    <Text style={[ui.small, { color: c.muted }]}>{t('Snippets isolados inserem o texto salvo exatamente. Outros snippets são expandidos uma vez antes da revisão.')}</Text>
  </Section>}
  {pending && <ActivityIndicator />}
  {!!error && <Text accessibilityRole="alert" style={[ui.small, { color: c.danger }]}>{t(error)}</Text>}
  </>;
}
