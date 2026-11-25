import { t } from "../i18n";
import { useEffect, useRef, useState } from 'react';
import { Text, type TextInput } from 'react-native';
import { DraftTextInput } from './draft-text-input';
import { Button, TextButton, ui, usePalette } from './ui';
import type { AccountSnapshot } from '../../modules/clarify-core';
import { report } from '../state/clarify';
import { AccountEndpointRecovery } from './account-endpoint-recovery';

export function AccountSignIn({ account, busy, command }: {
  account: AccountSnapshot; busy: boolean;
  command: (action: string, value?: string) => Promise<void>;
}) {
  const c = usePalette();
  const [emailSeed, setEmailSeed] = useState(account.email || '');
  const email = useRef(emailSeed);
  const [hasEmail, setHasEmail] = useState(!!emailSeed.trim());
  const [code, setCode] = useState('');
  const codeDraft = useRef('');
  const codeInput = useRef<TextInput>(null);
  const [social, setSocial] = useState('');
  const [cancelling, setCancelling] = useState(false);
  const [providerConfig, setProviderConfig] = useState<{ endpoint: string; ids: string[] }>();
  const endpoint = !account.pending && !account.endpointRecovery && account.endpoint?.startsWith('https://')
    ? account.endpoint : '';
  const providers = providerConfig?.endpoint === endpoint ? providerConfig.ids : [];
  useEffect(() => {
    if (!endpoint) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(`${endpoint}/_allauth/app/v1/config`, {
          credentials: 'omit', signal: controller.signal,
        });
        const config = response.ok ? await response.json() : null;
        const advertised = config?.data?.socialaccount?.providers;
        const ids = Array.isArray(advertised) ? advertised.flatMap(provider => (
          typeof provider?.id === 'string' && Array.isArray(provider.flows) && provider.flows.includes('provider_redirect')
            ? [provider.id] : []
        )) : [];
        if (!controller.signal.aborted) setProviderConfig({ endpoint, ids });
      } catch {
        if (!controller.signal.aborted) setProviderConfig({ endpoint, ids: [] });
      }
    })();
    return () => controller.abort();
  }, [endpoint]);
  const blocked = busy || !!social;
  const run = (action: string, value = '') => void command(action, value).catch(report);
  const input = { color: c.text, borderColor: c.controlBorder };
  const changeEmail = (value: string) => { email.current = value; setHasEmail(!!value.trim()); };
  const send = (value = email.current) => {
    changeEmail(value);
    setEmailSeed(value);
    if (!blocked && value.trim() && account.endpoint) run('login', value);
  };
  const changeCode = (value: string) => { codeDraft.current = value; setCode(value); };
  const confirm = () => {
    const value = codeDraft.current;
    if (busy || !value.trim()) return;
    run('confirm', value);
    changeCode('');
    codeInput.current?.clear();
  };
  const signIn = (provider: string) => {
    if (blocked || !providers.includes(provider)) return;
    setSocial(provider);
    void command('social', provider).catch(report).finally(() => { setSocial(''); setCancelling(false); });
  };
  const cancel = () => {
    setCancelling(true);
    void command('cancel-social').catch(error => { setCancelling(false); report(error); });
  };
  if (account.endpointRecovery) return <AccountEndpointRecovery account={account} busy={blocked} command={command} />;
  const socialButtons = [
    { id: 'google', label: t("Continuar com Google") },
    { id: 'microsoft', label: t("Continuar com Microsoft") },
    { id: 'github', label: t("Continuar com GitHub") },
  ].filter(({ id }) => providers.includes(id));
  return account.pending ? <>
    <Text style={[ui.small, { color: c.muted }]}>{t("Digite o código enviado para {v0}. O código vale por 10 minutos.", { v0: account.email })}</Text>
    <DraftTextInput inputRef={codeInput} selectionColor={c.text} testID="account.code" accessibilityLabel={t("Código da conta Clarify")} initialValue={code} onChangeText={changeCode} editable={!busy} textContentType="oneTimeCode" keyboardType="number-pad" maxLength={16} placeholder={t("Código")} placeholderTextColor={c.muted} style={[ui.input, input]} />
    <Button primary testID="account.verifyCode" loading={busy} disabled={!code.trim()} onPress={confirm}>{t("Confirmar código")}</Button>
    <TextButton testID="account.backToEmail" disabled={busy} onPress={() => run('logout')}>{t("Voltar")}</TextButton>
  </> : <>
    {socialButtons.map(({ id, label }) =>
      <Button key={id} testID={`account.social.${id}`} loading={social === id} disabled={blocked} onPress={() => signIn(id)}>{label}</Button>)}
    {social && <>
      <Text accessibilityLiveRegion="polite" style={[ui.small, { color: c.muted }]}>{t("Conclua a entrada na página do provedor.")}</Text>
      <TextButton disabled={cancelling} onPress={cancel}>{t("Cancelar")}</TextButton>
    </>}
    {socialButtons.length > 0 && <Text style={[ui.small, { color: c.muted, textAlign: 'center' }]}>{t("Ou continue com seu e-mail")}</Text>}
    <DraftTextInput selectionColor={c.text} testID="account.email" accessibilityLabel={t("E-mail da conta Clarify")} initialValue={emailSeed} onChangeText={changeEmail} editable={!blocked} autoCapitalize="none" autoCorrect={false} keyboardType="email-address" textContentType="emailAddress" returnKeyType="go" onSubmitEditing={event => send(event.nativeEvent.text)} maxLength={254} placeholder={t("E-mail")} placeholderTextColor={c.muted} style={[ui.input, input]} />
    <Button primary testID="account.requestCode" loading={busy && !social} disabled={blocked || !hasEmail || !account.endpoint} onPress={() => send()}>{t("Continuar")}</Button>
    <Text style={[ui.small, { color: c.muted }]}>{t("Enviaremos um código para entrar ou criar sua conta. Você não precisa de senha.")}</Text>
  </>;
}
