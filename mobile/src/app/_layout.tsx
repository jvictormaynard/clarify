import { t } from "../i18n";
import { DarkTheme, DefaultTheme, ThemeProvider, Stack } from 'expo-router';
import { ActivityIndicator, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { Button, usePalette } from '../components/ui';
import { ClarifyProvider, report, useClarify } from '../state/clarify';

function Navigation() {
  const c = usePalette();
  const { account, onboardingRequired, setupError, refreshOnboarding, refreshAccount } = useClarify();
  if (onboardingRequired === null || !account) return <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: c.background }}>
    <ActivityIndicator />
    {(setupError || !account) && <Button onPress={() => { void refreshOnboarding(); void refreshAccount().catch(report); }}>{t("Tentar carregar novamente")}</Button>}
  </View>;
  const needsSetup = onboardingRequired || !account.signedIn;
  return <Stack screenOptions={{ headerShown: false, animation: 'fade', headerBackButtonDisplayMode: 'minimal' }}>
    <Stack.Protected guard={needsSetup}><Stack.Screen name="onboarding" /></Stack.Protected>
    <Stack.Protected guard={!needsSetup}>
      <Stack.Screen name="(tabs)" />
      <Stack.Screen name="settings" options={{ headerShown: true, title: t("Ajustes"), animation: 'slide_from_right' }} />
      <Stack.Screen name="sign-in" options={{ headerShown: true, title: t("Conta"), animation: 'slide_from_right' }} />
    </Stack.Protected>
  </Stack>;
}

export default function Layout() {
  const c = usePalette();
  return <ClarifyProvider><ThemeProvider value={c.dark ? DarkTheme : DefaultTheme}>
    <StatusBar style={c.dark ? 'light' : 'dark'} />
    <Navigation />
  </ThemeProvider></ClarifyProvider>;
}
