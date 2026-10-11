import type { ReactNode } from 'react';
import { Pressable, StyleSheet, Text, useColorScheme, View, type StyleProp, type ViewStyle } from 'react-native';

export function usePalette() {
  const dark = useColorScheme() === 'dark';
  return { dark, background: dark ? '#111113' : '#f2f2f7', card: dark ? '#1c1c1e' : '#fff', text: dark ? '#f5f5f7' : '#171719', muted: dark ? '#a4a4ab' : '#6c6c74', line: dark ? '#343438' : '#dedee3', accent: '#007aff', danger: dark ? '#ff6961' : '#c42b29' };
}
export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  const c = usePalette();
  return <View style={[ui.card, { backgroundColor: c.card }, style]}>{children}</View>;
}
export function Title({ children, subtitle }: { children: ReactNode; subtitle?: string }) {
  const c = usePalette();
  return <View style={ui.heading}><Text accessibilityRole="header" style={[ui.title, { color: c.text }]}>{children}</Text>{subtitle && <Text style={[ui.body, { color: c.muted }]}>{subtitle}</Text>}</View>;
}
export function Button({ children, onPress, disabled = false, destructive = false }: { children: string; onPress: () => void; disabled?: boolean; destructive?: boolean }) {
  const c = usePalette();
  return <Pressable accessibilityRole="button" accessibilityState={{ disabled }} disabled={disabled} onPress={onPress}
    style={({ pressed }) => [ui.button, { backgroundColor: c.card, opacity: disabled ? 0.35 : pressed ? 0.65 : 1 }]}>
    <Text style={[ui.buttonText, { color: destructive ? c.danger : c.accent }]}>{children}</Text>
  </Pressable>;
}
export function TextButton({ children, onPress, disabled = false }: { children: string; onPress: () => void; disabled?: boolean }) {
  const c = usePalette();
  return <Pressable accessibilityRole="button" accessibilityState={{ disabled }} disabled={disabled} onPress={onPress}
    style={({ pressed }) => ({ minHeight: 44, alignItems: 'center', justifyContent: 'center', opacity: disabled ? 0.35 : pressed ? 0.65 : 1 })}>
    <Text style={[ui.small, { color: c.accent }]}>{children}</Text>
  </Pressable>;
}
export const ui = StyleSheet.create({
  content: { paddingHorizontal: 20, paddingTop: 20, paddingBottom: 36, gap: 16 },
  heading: { gap: 8, marginBottom: 8 }, title: { fontSize: 32, fontWeight: '700', letterSpacing: -0.8 },
  section: { fontSize: 20, fontWeight: '600', letterSpacing: -0.3, marginTop: 8 },
  body: { fontSize: 15, lineHeight: 22 }, small: { fontSize: 13, lineHeight: 19 },
  card: { borderRadius: 18, padding: 18, gap: 12 }, row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  button: { minHeight: 48, paddingHorizontal: 16, paddingVertical: 13, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  buttonText: { fontSize: 16, fontWeight: '500' }, input: { minHeight: 48, borderWidth: StyleSheet.hairlineWidth, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, fontSize: 16 },
});
