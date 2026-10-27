import { t } from "../i18n";
import { ActivityIndicator, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { AccountSignIn } from '../components/account-sign-in';
import { ClarifyLogo } from '../components/clarify-logo';
import { Button, KeyboardPage, Title, ui, usePalette } from '../components/ui';
import { isBusy, report, useClarify } from '../state/clarify';

import { ProcessingChoice, ComputerConnectionCard } from '../components/computer-connection';

export default function SignIn() {
  const c = usePalette();
  const { state, account, accountBusy, accountCommand, refreshAccount } = useClarify();
  const busy = isBusy(state) || accountBusy || !!account?.busy;
  return <SafeAreaView style={{ flex: 1, backgroundColor: c.background }}><KeyboardPage contentContainerStyle={{ justifyContent: 'center' }}>
    <View style={{ gap: 20, width: '100%', maxWidth: 520, alignSelf: 'center' }}>
      <ClarifyLogo size={40} /><Title>{t('Escolha como usar o Clarify')}</Title>
      {account?.mode !== 'computer' && <Text style={[ui.body, { color: c.muted }]}>{t("O Clarify processa áudio, texto e palavras ativas do dicionário.")}</Text>}
      <View style={{ gap: 16 }}>{!account ? <><ActivityIndicator /><Button onPress={() => void refreshAccount().catch(report)}>{t("Tentar carregar novamente")}</Button></> : <>
        <ProcessingChoice />
        {account.mode === 'computer' ? <ComputerConnectionCard /> : <AccountSignIn account={account} busy={busy} command={accountCommand} />}
        {account.error && <Text accessibilityRole="alert" style={[ui.small, { color: c.danger }]}>{t(account.error)}</Text>}
      </>}</View>
    </View>
  </KeyboardPage></SafeAreaView>;
}
