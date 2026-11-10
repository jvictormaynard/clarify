import { useCallback, useRef, useState } from 'react';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Text } from 'react-native';
import Core, { type DictationPolicy, type OutputLanguage } from '../../modules/clarify-core';
import { TextButton, ChoiceRow, Section, ui, usePalette } from './ui';
import { useClarify } from '../state/clarify';
import { errorMessage } from '../errors';
import { t } from '../i18n';

export function DictationPolicyControls({ outputLanguage, tone, more }: { outputLanguage?: OutputLanguage; tone?: React.ReactNode; more?: React.ReactNode }) {
  const c = usePalette();
  const { account } = useClarify();
  const context = account?.historyContext ?? '';
  const catalog = account?.mode === 'computer' ? account.computer : account;
  const capabilities = catalog?.processingContract;
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
  const modes = [
    { value: 'legacy', label: 'Usar configuração do destino' },
    { value: 'natural', label: 'Usar instruções de ditado' }, { value: 'clarity', label: 'Revisar clareza' },
    { value: 'preserve', label: 'Manter minhas palavras' }, { value: 'light', label: 'Ajustar apenas espaços' },
    { value: 'action', label: 'Aplicar ação de texto' },
  ] as const;
  const selected = catalog?.textActions.find(action => action.id === policy?.actionID && action.revision === policy?.actionRevision);
  const editing = capabilities?.dictation_editing;
  const editingMode = (policy && ['legacy', 'natural'].includes(policy.mode) && outputLanguage && outputLanguage !== 'auto'
    ? `${policy.mode}_translated` : policy?.mode) as 'legacy' | 'natural' | 'clarity' | 'action' | 'legacy_translated' | 'natural_translated';
  const toneAllowed = policy && !['preserve', 'light'].includes(policy.mode) && capabilities?.cleanup_levels?.includes('clarity') &&
    (account?.mode === 'computer' ? editing?.[editingMode] === true : editing?.[editingMode] !== false) &&
    (policy.mode !== 'action' || (selected?.enabled && selected.ready));
  function choices(values: typeof modes[number][]) { return values.map(mode => <ChoiceRow key={mode.value} testID={`output.policy.${mode.value}`} title={t(mode.label)}
      selected={(choosing ? 'action' : policy?.mode) === mode.value}
      disabled={!policy || pending || (mode.value === 'legacy' ? false : mode.value === 'natural' ? account?.mode === 'computer' && !capabilities?.explicit_dictation_policy
        : mode.value === 'action' ? !capabilities?.dictation_actions : (!capabilities?.explicit_dictation_policy || !capabilities?.cleanup_levels?.includes(mode.value)))}
      onPress={() => { if (mode.value === 'action') setChoosing(true); else void save(mode.value); }} />); }
  return <>
    <Section title={t('Edição do texto')}>
      {choices(modes.filter(mode => ['clarity', 'preserve'].includes(mode.value)))}
      {policy && !['clarity', 'preserve'].includes(policy.mode) && <Text style={[ui.small, { color: c.muted }]}>{t(modes.find(mode => mode.value === policy.mode)?.label ?? '')}</Text>}
    </Section>
    {toneAllowed && tone}
    <TextButton testID="output.more" expanded={expanded} onPress={() => setExpanded(!expanded)}>{t('Mais opções')}</TextButton>
    {expanded && <Section title={t('Mais opções')}>
    <Text style={[ui.small, { color: c.muted }]}>{t('Idioma e tom se aplicam à revisão e às ações de texto.')}</Text>
    {more}
    {choices(modes.filter(mode => !['clarity', 'preserve'].includes(mode.value)))}
    {(choosing || policy?.mode === 'action') && <>
      {catalog?.textActions.filter(action => action.enabled).map(action => <ChoiceRow key={action.id} testID={`output.policy.action.${action.id}`}
        title={action.name} selected={policy?.actionID === action.id}
        disabled={pending || !action.ready || (action.kind === 'translation' && (!outputLanguage || outputLanguage === 'auto'))}
        onPress={() => void save('action', action.id, action.revision, outputLanguage ?? 'auto')} />)}
      {policy?.mode === 'action' && !selected && <Text accessibilityRole="alert" style={[ui.small, { color: c.danger }]}>{t('A ação mudou. Atualize as ações.')}</Text>}
      <Text style={[ui.small, { color: c.muted }]}>{t('Escolha uma ação para salvar. Até lá, a configuração anterior continua ativa.')}</Text>
      <Text style={[ui.small, { color: c.muted }]}>{t('A tradução usa o idioma de saída acima. Selecione um idioma antes de escolher a ação.')}</Text>
    </>}
    <Text style={[ui.small, { color: c.muted }]}>{t('Snippets isolados inserem o texto salvo exatamente. Outros snippets são expandidos uma vez antes da revisão.')}</Text>
  </Section>}
  {pending && <ActivityIndicator />}
  {!!error && <Text accessibilityRole="alert" style={[ui.small, { color: c.danger }]}>{t(error)}</Text>}
  </>;
}
