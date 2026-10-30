import { useEffect, useRef, useState, type ReactNode } from 'react';
import { AccessibilityInfo, ActivityIndicator, Animated, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, useColorScheme, View, type StyleProp, type ViewStyle } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { t } from '../i18n';
import { SymbolView, type SymbolViewProps } from 'expo-symbols';

export function usePalette() {
  const dark = useColorScheme() === 'dark';
  return { dark, background: dark ? '#111111' : '#f5f5f5', card: dark ? '#1c1c1c' : '#ffffff',
    text: dark ? '#f5f5f5' : '#181818', muted: dark ? '#a6a6a6' : '#666666', line: dark ? '#3d3d3d' : '#d5d5d5', controlBorder: dark ? '#777777' : '#888888',
    accent: dark ? '#f5f5f5' : '#181818', accentSoft: dark ? '#292929' : '#ededed', danger: dark ? '#f5f5f5' : '#181818' };
}

export function useReducedMotion() {
  const [reduced, setReduced] = useState(true);
  useEffect(() => {
    let active = true;
    void AccessibilityInfo.isReduceMotionEnabled().then(value => { if (active) setReduced(value); }).catch(() => {});
    const subscription = AccessibilityInfo.addEventListener('reduceMotionChanged', setReduced);
    return () => { active = false; subscription.remove(); };
  }, []);
  return reduced;
}

export function StepContent({ step, children }: { step: string; children: ReactNode }) {
  const reduced = useReducedMotion();
  const [opacity] = useState(() => new Animated.Value(1));
  const previousStep = useRef(step);
  useEffect(() => {
    const changed = previousStep.current !== step;
    previousStep.current = step;
    if (reduced || !changed) { opacity.setValue(1); return; }
    opacity.setValue(0);
    const animation = Animated.timing(opacity, { toValue: 1, duration: 160, useNativeDriver: true });
    animation.start();
    return () => animation.stop();
  }, [step, reduced, opacity]);
  return <Animated.View style={{ gap: 24, opacity }}>{children}</Animated.View>;
}

export function KeyboardPage({ children, contentContainerStyle }: { children: ReactNode; contentContainerStyle?: StyleProp<ViewStyle> }) {
  return <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
    <ScrollView testID="app.keyboard-page" style={{ flex: 1 }} contentContainerStyle={[ui.content, { flexGrow: 1 }, contentContainerStyle]}
      keyboardShouldPersistTaps="handled" keyboardDismissMode="interactive">
      {children}
    </ScrollView>
  </KeyboardAvoidingView>;
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  const c = usePalette();
  return <View style={[ui.card, { backgroundColor: c.card }, style]}>{children}</View>;
}
export function Title({ children, subtitle }: { children: ReactNode; subtitle?: string }) {
  const c = usePalette();
  return <View style={ui.heading}><Text accessibilityRole="header" style={[ui.title, { color: c.text }]}>{children}</Text>{subtitle && <Text style={[ui.body, { color: c.muted }]}>{subtitle}</Text>}</View>;
}
export function Button({ children, onPress, disabled = false, destructive = false, loading = false, primary = false, testID }: {
  children: string; onPress: () => void; disabled?: boolean; destructive?: boolean; loading?: boolean; primary?: boolean; testID?: string;
}) {
  const c = usePalette();
  const color = primary ? c.background : destructive ? c.danger : c.text;
  return <Pressable testID={testID} accessibilityRole="button" accessibilityState={{ disabled: disabled || loading, busy: loading }} disabled={disabled || loading} onPress={onPress}
    style={({ pressed }) => [ui.button, { borderWidth: StyleSheet.hairlineWidth, borderColor: primary ? c.text : c.controlBorder,
      backgroundColor: primary ? c.text : c.card, opacity: disabled ? 0.4 : pressed ? 0.65 : 1 }]}>
    <Text style={[ui.buttonText, { color }]}>{children}</Text>
    {loading && <ActivityIndicator size="small" color={color} style={{ position: 'absolute', right: 16 }} />}
  </Pressable>;
}
export function TextButton({ children, onPress, disabled = false, testID, expanded }: { children: string; onPress: () => void; disabled?: boolean; testID?: string; expanded?: boolean }) {
  const c = usePalette();
  return <Pressable testID={testID} accessibilityRole="button" accessibilityState={{ disabled, expanded }} disabled={disabled} onPress={onPress}
    style={({ pressed }) => ({ minHeight: 44, paddingHorizontal: 8, alignItems: 'center', justifyContent: 'center', opacity: disabled ? 0.4 : pressed ? 0.65 : 1 })}>
    <Text style={[ui.body, { color: c.text, fontWeight: '500' }]}>{children}</Text>
  </Pressable>;
}
export const ui = StyleSheet.create({
  content: { width: '100%', maxWidth: 640, alignSelf: 'center', paddingHorizontal: 20, paddingTop: 24, paddingBottom: 36, gap: 24 },
  heading: { gap: 8, marginBottom: 8 }, title: { fontSize: 32, fontWeight: '700', letterSpacing: -0.8 },
  section: { fontSize: 20, fontWeight: '600', letterSpacing: -0.3, marginTop: 8 },
  body: { fontSize: 16, lineHeight: 23 }, small: { fontSize: 13, lineHeight: 19 },
  card: { borderRadius: 14, padding: 18, gap: 12 }, row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  button: { minHeight: 48, paddingHorizontal: 16, paddingVertical: 13, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  buttonText: { fontSize: 16, fontWeight: '600' }, input: { minHeight: 48, borderWidth: StyleSheet.hairlineWidth, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, fontSize: 16 },
});

export function ScreenHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return <View style={{ gap: 8, marginBottom: 8 }}>
    <View style={[ui.row, { alignItems: 'flex-start' }]}><View style={{ flex: 1 }}><Title subtitle={subtitle}>{title}</Title></View>{action}</View>
  </View>;
}

export function Section({ title, detail, children }: { title: string; detail?: string; children: ReactNode }) {
  const c = usePalette();
  return <View style={{ gap: 10 }}>
    <Text accessibilityRole="header" style={[ui.section, { color: c.text, marginTop: 4 }]}>{title}</Text>
    {detail && <Text style={[ui.small, { color: c.muted }]}>{detail}</Text>}
    <Card>{children}</Card>
  </View>;
}

export function NavigationRow({ title, detail, icon, onPress, testID }: { title: string; detail?: string; icon: SymbolViewProps['name']; onPress: () => void; testID?: string }) {
  const c = usePalette();
  return <Pressable testID={testID} accessibilityRole="button" onPress={onPress}
    style={({ pressed }) => ({ minHeight: 52, flexDirection: 'row', alignItems: 'center', gap: 12, opacity: pressed ? 0.65 : 1 })}>
    <View style={{ width: 24, alignItems: 'center', justifyContent: 'center' }}>
      <SymbolView name={icon} size={19} tintColor={c.accent} accessible={false} />
    </View>
    <View style={{ flex: 1, gap: 3 }}><Text style={[ui.body, { color: c.text, fontWeight: '600' }]}>{title}</Text>{detail && <Text style={[ui.small, { color: c.muted }]}>{detail}</Text>}</View>
    <SymbolView name="chevron.right" size={13} tintColor={c.muted} accessible={false} />
  </Pressable>;
}

export function EmptyState({ title, detail, children }: { title: string; detail: string; children?: ReactNode }) {
  const c = usePalette();
  return <View style={{ alignItems: 'flex-start', gap: 12, paddingVertical: 16 }}>
    <Text accessibilityRole="header" style={[ui.section, { color: c.text, marginTop: 0 }]}>{title}</Text>
    <Text style={[ui.body, { color: c.muted }]}>{detail}</Text>
    {children}
  </View>;
}

export function ChoiceRow({ title, detail, selected, disabled = false, onPress, testID }: {
  title: string; detail?: string; selected: boolean; disabled?: boolean; onPress: () => void; testID?: string;
}) {
  const c = usePalette();
  return <Pressable testID={testID} accessibilityRole="radio" accessibilityLabel={title}
    accessibilityState={{ selected, checked: selected, disabled }} disabled={disabled} onPress={onPress}
    style={({ pressed }) => ({ minHeight: 48, paddingVertical: 12, gap: 8, flexDirection: 'row', alignItems: 'center', opacity: disabled ? 0.45 : pressed ? 0.65 : 1 })}>
    <View style={{ flex: 1 }}><Text style={[ui.body, { color: c.text }]}>{title}</Text>{detail && <Text style={[ui.small, { color: c.muted }]}>{detail}</Text>}</View>
    {selected && <SymbolView name="checkmark" tintColor={c.text} size={18} accessible={false} />}
  </Pressable>;
}

export function NativeSheet({ visible, title, onClose, children }: { visible: boolean; title: string; onClose: () => void; children: ReactNode }) {
  const c = usePalette();
  const reduced = useReducedMotion();
  return <Modal visible={visible} presentationStyle="pageSheet" animationType={reduced ? 'none' : 'slide'} onRequestClose={onClose}>
    <SafeAreaView style={{ flex: 1, backgroundColor: c.background }}>
      <View style={[ui.content, ui.row, { alignItems: 'flex-start', paddingTop: 12, paddingBottom: 8 }]}>
        <Text accessibilityRole="header" style={[ui.section, { color: c.text, flex: 1 }]}>{title}</Text>
        <Pressable accessibilityRole="button" accessibilityLabel={t('Fechar')} onPress={onClose}
          style={({ pressed }) => ({ width: 44, height: 44, flexShrink: 0, alignItems: 'center', justifyContent: 'center', opacity: pressed ? 0.65 : 1 })}>
          <SymbolView name="xmark" size={20} tintColor={c.text} accessible={false} />
        </Pressable>
      </View>
      <ScrollView contentContainerStyle={[ui.content, { paddingTop: 8 }]} keyboardShouldPersistTaps="handled">{children}</ScrollView>
    </SafeAreaView>
  </Modal>;
}

export function TableRow({ children, first, last, onPress, disabled = false, accessibilityLabel }: {
  children: ReactNode; first: boolean; last: boolean; onPress: () => void; disabled?: boolean; accessibilityLabel?: string;
}) {
  const c = usePalette();
  return <Pressable accessibilityRole="button" accessibilityLabel={accessibilityLabel} disabled={disabled} onPress={onPress}
    style={({ pressed }) => ({ backgroundColor: c.card, paddingHorizontal: 18, paddingVertical: 16, minHeight: 64, gap: 6,
      borderTopLeftRadius: first ? 18 : 0, borderTopRightRadius: first ? 18 : 0,
      borderBottomLeftRadius: last ? 18 : 0, borderBottomRightRadius: last ? 18 : 0,
      borderBottomWidth: last ? 0 : StyleSheet.hairlineWidth, borderBottomColor: c.line,
      opacity: pressed ? 0.65 : 1 })}>{children}</Pressable>;
}
export function ModalHeader({ title, cancelLabel, saveLabel, onCancel, onSave, disabled, loading, busy = loading }: {
  title: string; cancelLabel: string; saveLabel: string; onCancel: () => void; onSave: () => void; disabled: boolean; loading: boolean; busy?: boolean;
}) {
  const c = usePalette();
  const action = (label: string, onPress: () => void, blocked: boolean, saving = false) =>
    <Pressable accessibilityRole="button" accessibilityLabel={label} accessibilityState={{ disabled: blocked, busy: saving }}
      disabled={blocked} onPress={onPress} style={({ pressed }) => ({ width: 84, minHeight: 44, alignItems: 'center', justifyContent: 'center', opacity: blocked && !saving ? 0.35 : pressed ? 0.65 : 1 })}>
      <Text numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8} style={{ fontSize: 17, color: c.accent, opacity: saving ? 0 : 1 }}>{label}</Text>
      {saving && <ActivityIndicator color={c.accent} style={{ position: 'absolute' }} />}
    </Pressable>;
  return <View style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: 8, minHeight: 56 }}>
    {action(cancelLabel, onCancel, busy)}
    <Text accessibilityRole="header" numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8}
      style={{ flex: 1, textAlign: 'center', fontSize: 17, fontWeight: '600', color: c.text }}>{title}</Text>
    {action(saveLabel, onSave, disabled || loading, loading)}
  </View>;
}
