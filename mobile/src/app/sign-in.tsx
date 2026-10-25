import { t } from "../i18n";
import { useEffect } from 'react';
import { router } from 'expo-router';
import { ActivityIndicator, ScrollView, Text, View } from 'react-native';
import { AccountSignIn } from '../components/account-sign-in';
import { ClarifyLogo } from '../components/clarify-logo';
import { Button, Card, Title, ui, usePalette } from '../components/ui';
import { isBusy, report, useClarify } from '../state/clarify';

export default function SignIn() {
  const c = usePalette();
  const { state, account, accountBusy, accountCommand, refreshAccount } = useClarify();
  const busy = isBusy(state) || accountBusy || !!account?.busy;
  useEffect(() => {
    if (account?.signedIn) {
      if (router.canGoBack()) router.back();
      else router.replace('/account');
    }
  }, [account?.signedIn]);
  return <ScrollView style={{ flex: 1, backgroundColor: c.background }} contentContainerStyle={[ui.content, { flexGrow: 1, justifyContent: 'center' }]} keyboardShouldPersistTaps="handled" keyboardDismissMode="interactive">
    <View style={{ gap: 20, width: '100%', maxWidth: 520, alignSelf: 'center' }}>
      <ClarifyLogo /><Title>{t("Entre no Clarify")}</Title>
      <Card>{!account ? <><ActivityIndicator /><Button onPress={() => void refreshAccount().catch(report)}>{t("Tentar carregar novamente")}</Button></> : <>
        <AccountSignIn account={account} busy={busy} command={accountCommand} />
        {account.error && <Text accessibilityRole="alert" style={[ui.small, { color: c.danger }]}>{t(account.error)}</Text>}
      </>}</Card>
    </View>
  </ScrollView>;
}
