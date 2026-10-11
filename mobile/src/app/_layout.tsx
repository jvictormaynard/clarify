import { DarkTheme, DefaultTheme, ThemeProvider } from 'expo-router';
import { NativeTabs } from 'expo-router/unstable-native-tabs';
import { StatusBar } from 'expo-status-bar';
import { usePalette } from '../components/ui';
import { ClarifyProvider } from '../state/clarify';

export default function Layout() {
  const c = usePalette();
  return <ClarifyProvider><ThemeProvider value={c.dark ? DarkTheme : DefaultTheme}>
    <StatusBar style={c.dark ? 'light' : 'dark'} />
    <NativeTabs>
      <NativeTabs.Trigger name="index"><NativeTabs.Trigger.Label>Home</NativeTabs.Trigger.Label><NativeTabs.Trigger.Icon sf={{ default: 'house', selected: 'house.fill' }} /></NativeTabs.Trigger>
      <NativeTabs.Trigger name="dictionary"><NativeTabs.Trigger.Label>Dicionário</NativeTabs.Trigger.Label><NativeTabs.Trigger.Icon sf={{ default: 'book', selected: 'book.fill' }} /></NativeTabs.Trigger>
      <NativeTabs.Trigger name="settings"><NativeTabs.Trigger.Label>Ajustes</NativeTabs.Trigger.Label><NativeTabs.Trigger.Icon sf="gearshape" /></NativeTabs.Trigger>
    </NativeTabs>
  </ThemeProvider></ClarifyProvider>;
}
