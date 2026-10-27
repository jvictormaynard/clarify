import { t } from "../i18n";
import { DarkTheme, DefaultTheme, ThemeProvider, Stack } from 'expo-router';
import { ActivityIndicator, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { Button, usePalette, useReducedMotion } from '../components/ui';
import { ClarifyProvider, report, useClarify } from '../state/clarify';

import { processingAvailable } from '../processing';

function Navigation() {
  const c = usePalette();
  const reducedMotion = useReducedMotion();
  const { account, onboardingRequired, setupError, refreshOnboarding, refreshAccount } = useClarify();
  if (onboardingRequired === null || !account) return <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: c.background }}>
    <ActivityIndicator />
    {(setupError || !account) && <Button onPress={() => { void refreshOnboarding(); void refreshAccount().catch(report); }}>{t("Tentar carregar novamente")}</Button>}
  </View>;
  const showOnboarding = onboardingRequired;
  const showSignIn = !showOnboarding && !processingAvailable(account);
  return <Stack screenOptions={{ headerShown: false, animation: reducedMotion ? 'none' : 'fade', headerBackButtonDisplayMode: 'minimal' }}>
    <Stack.Protected guard={showOnboarding}><Stack.Screen name="onboarding" /></Stack.Protected>
    <Stack.Protected guard={showSignIn}><Stack.Screen name="sign-in" options={{ animation: reducedMotion ? 'none' : 'fade' }} /></Stack.Protected>
    <Stack.Protected guard={!showOnboarding && processingAvailable(account)}>
      <Stack.Screen name="(tabs)" />
      <Stack.Screen name="settings" options={{ headerShown: true, title: t("Ajustes"), animation: reducedMotion ? 'none' : 'slide_from_right' }} />
      <Stack.Screen name="guide" options={{ headerShown: true, title: t("Como usar"), animation: reducedMotion ? 'none' : 'slide_from_right' }} />
    </Stack.Protected>
  </Stack>;
}

export default function Layout() {
  const c = usePalette();
  const theme = c.dark ? DarkTheme : DefaultTheme;
  return <ClarifyProvider><ThemeProvider value={{ ...theme, colors: { ...theme.colors, primary: c.text, background: c.background, card: c.card, text: c.text, border: c.line, notification: c.text } }}>
    <StatusBar style={c.dark ? 'light' : 'dark'} />
    <Navigation />
  </ThemeProvider></ClarifyProvider>;
}
