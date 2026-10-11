import { DarkTheme, DefaultTheme, ThemeProvider, Stack } from 'expo-router';
import { ActivityIndicator, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { Button, usePalette } from '../components/ui';
import { ClarifyProvider, useClarify } from '../state/clarify';

function Navigation() {
  const c = usePalette();
  const { onboardingRequired, setupError, refreshOnboarding } = useClarify();
  if (onboardingRequired === null) return <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: c.background }}>
    {setupError ? <Button onPress={() => void refreshOnboarding()}>Tentar carregar novamente</Button> : <ActivityIndicator />}
  </View>;
  return <Stack screenOptions={{ headerShown: false, animation: 'fade' }}>
    <Stack.Protected guard={onboardingRequired}><Stack.Screen name="onboarding" /></Stack.Protected>
    <Stack.Protected guard={!onboardingRequired}><Stack.Screen name="(tabs)" /></Stack.Protected>
  </Stack>;
}

export default function Layout() {
  const c = usePalette();
  return <ClarifyProvider><ThemeProvider value={c.dark ? DarkTheme : DefaultTheme}>
    <StatusBar style={c.dark ? 'light' : 'dark'} />
    <Navigation />
  </ThemeProvider></ClarifyProvider>;
}
