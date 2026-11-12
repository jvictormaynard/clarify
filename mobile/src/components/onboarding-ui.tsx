import { useEffect, useState, type ReactNode } from 'react';
import { useIsFocused } from 'expo-router';
import { Animated, AppState, Easing, Image, Linking, Pressable, StyleSheet, Text, View } from 'react-native';
import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { t, uiLanguage } from '../i18n';
import { report } from '../state/clarify';
import { ui, usePalette, useReducedMotion } from './ui';

export const onboardingStyles = StyleSheet.create({
  footer: { marginTop: 'auto', paddingTop: 24, gap: 12 },
});

export { Title as OnboardingTitle } from './ui';

export function OnboardingHeader({ title, onBack, disabled = false, testID }: { title: string; onBack: () => void; disabled?: boolean; testID?: string }) {
  const c = usePalette();
  return <View style={{ minHeight: 52, flexDirection: 'row', alignItems: 'center', gap: 12 }}>
    <Pressable testID={testID} accessibilityRole="button" accessibilityLabel={t('Voltar')} disabled={disabled} onPress={onBack}
      style={({ pressed }) => ({ width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center', backgroundColor: c.card, borderWidth: 1, borderColor: c.line, opacity: disabled ? 0.4 : pressed ? 0.65 : 1 })}>
      <SymbolView name="chevron.left" tintColor={c.text} size={22} accessible={false} />
    </Pressable>
    <Text style={[ui.body, { flex: 1, textAlign: 'center', color: c.muted }]}>{title}</Text>
    <View style={{ width: 44 }} />
  </View>;
}

export function PrivacyNote({ children }: { children: ReactNode }) {
  const c = usePalette();
  return <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 12, padding: 14, borderRadius: 14, borderWidth: 1, borderColor: c.line, backgroundColor: c.accentSoft }}>
    <SymbolView name="checkmark.shield" size={20} tintColor={c.accent} accessible={false} />
    <Text style={[ui.small, { color: c.muted, flex: 1 }]}>{children}</Text>
  </View>;
}

// Exported from desktop IPhoneDemo and its 12-second CSS timeline, in each UI language.
const demos = {
  pt: { animation: require('../../assets/onboarding/iphone-demo-pt.gif'), still: require('../../assets/onboarding/iphone-demo-pt.png') },
  en: { animation: require('../../assets/onboarding/iphone-demo-en.gif'), still: require('../../assets/onboarding/iphone-demo-en.png') },
  es: { animation: require('../../assets/onboarding/iphone-demo-es.gif'), still: require('../../assets/onboarding/iphone-demo-es.png') },
};
export function OnboardingDemo() {
  const reduced = useReducedMotion();
  const demo = demos[uiLanguage];
  return <Image source={reduced ? demo.still : demo.animation} resizeMode="cover" accessible={false}
    style={{ width: '100%', aspectRatio: 393 / 150 }} />;
}

export function WelcomeBenefits() {
  const c = usePalette();
  const rows: { icon: SymbolViewProps['name']; title: string; detail: string }[] = [
    { icon: 'mic', title: 'Fale em qualquer aplicativo', detail: 'Dite pelo teclado Clarify.' },
    { icon: 'square.and.pencil', title: 'Texto revisado enquanto você fala', detail: 'Menos hesitações. Pontuação no lugar.' },
    { icon: 'globe', title: 'Vários idiomas', detail: 'Fale nos idiomas que você usa.' },
  ];
  return <View style={{ gap: 16 }}>{rows.map(row => <View key={row.title} style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 14 }}>
    <View style={{ width: 40, height: 40, alignItems: 'center', justifyContent: 'center', borderRadius: 12, backgroundColor: c.accentSoft }}>
      <SymbolView name={row.icon} size={23} tintColor={c.accent} accessible={false} />
    </View>
    <View style={{ flex: 1, gap: 3 }}><Text style={[ui.body, { color: c.text, fontWeight: '500' }]}>{t(row.title)}</Text><Text style={[ui.small, { color: c.muted }]}>{t(row.detail)}</Text></View>
  </View>)}</View>;
}

export function PrivacyLink() {
  const c = usePalette();
  return <Pressable accessibilityRole="link" onPress={() => void Linking.openURL('https://github.com/jvictormaynard/clarify/blob/main/PRIVACY.md').catch(report)}
    style={{ minHeight: 44, justifyContent: 'center' }}>
    <Text style={[ui.small, { color: c.accent, textDecorationLine: 'underline' }]}>{t('Leia o aviso de privacidade do Clarify.')}</Text>
  </Pressable>;
}

export function KeyboardSetupIllustration() {
  const c = usePalette();
  const reduced = useReducedMotion();
  const focused = useIsFocused();
  const [timeline] = useState(() => new Animated.Value(0));
  useEffect(() => {
    if (reduced || !focused) { timeline.setValue(reduced ? 1 : 0); return; }
    let animation: Animated.CompositeAnimation | undefined;
    const sync = (state: string) => {
      animation?.stop();
      timeline.setValue(0);
      if (state !== 'active') return;
      animation = Animated.loop(Animated.timing(timeline, {
        toValue: 1, duration: 10000, easing: Easing.linear, useNativeDriver: true, isInteraction: false,
      }));
      animation.start();
    };
    sync(AppState.currentState);
    const listener = AppState.addEventListener('change', sync);
    return () => { listener.remove(); animation?.stop(); };
  }, [focused, reduced, timeline]);
  const steps = [t('Teclados'), 'Clarify', t('Permitir Acesso Total'), t('Permitir Acesso Total para o teclado Clarify?')];
  return <View style={{ gap: 10 }}>{steps.map((label, index) => {
    const tap = [0.1, 0.26, 0.5, 0.74][index];
    const opacity = timeline.interpolate({ inputRange: [0, tap - 0.04, tap, tap + 0.06, 1], outputRange: [0, 0, 0.5, 0, 0] });
    const scale = timeline.interpolate({ inputRange: [0, tap - 0.04, tap + 0.06, 1], outputRange: [0.7, 0.7, 1.3, 1.3] });
    const activated = timeline.interpolate({ inputRange: [0, tap, tap + 0.04, 1], outputRange: [0, 0, 1, 1] });
    return <View key={label} style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 12 }}>
      <View style={{ width: 28, height: 28, marginTop: 7, borderRadius: 14, backgroundColor: c.accent, alignItems: 'center', justifyContent: 'center' }}>
        <Text style={{ color: c.background, fontSize: 15 }}>{index + 1}</Text>
      </View>
      <View style={{ flex: 1, minHeight: 44, padding: 12, borderRadius: ui.card.borderRadius, borderWidth: 1, borderColor: c.line, backgroundColor: c.card, gap: 12 }}>
        <View style={ui.row}><Text style={[ui.body, { flex: 1, color: c.text, fontWeight: index === 3 ? '600' : '400' }]}>{label}</Text>
          {index === 0 ? <SymbolView name="chevron.right" tintColor={c.muted} size={16} accessible={false} /> : index < 3 ?
            <View accessible={false} style={{ width: 42, height: 25, borderRadius: 14, backgroundColor: c.accentSoft, overflow: 'hidden' }}>
              <Animated.View style={{ ...StyleSheet.absoluteFill, backgroundColor: '#34c759', opacity: activated }} />
              <Animated.View style={{ position: 'absolute', top: 2, left: 2, width: 21, height: 21, borderRadius: 11, backgroundColor: '#ffffff', transform: [{ translateX: timeline.interpolate({ inputRange: [0, tap, tap + 0.04, 1], outputRange: [0, 0, 17, 17] }) }] }} />
            </View> : null}
        </View>
        {index === 3 && <View style={ui.row}>{['Não permitir', 'Permitir'].map((text, button) => <View key={text} style={{ flex: 1, borderRadius: ui.button.borderRadius, overflow: 'hidden', backgroundColor: c.accentSoft }}>
          {button === 1 && <Animated.View style={{ ...StyleSheet.absoluteFill, backgroundColor: c.text, opacity: activated }} />}
          <Text style={[ui.small, { textAlign: 'center', padding: 9, color: c.text }]}>{t(text)}</Text>
          {button === 1 && <Animated.View accessible={false} importantForAccessibility="no-hide-descendants" style={{ ...StyleSheet.absoluteFill, justifyContent: 'center', opacity: activated }}><Text style={[ui.small, { textAlign: 'center', padding: 9, color: c.background }]}>{t(text)}</Text></Animated.View>}
        </View>)}</View>}
        <Animated.View pointerEvents="none" accessible={false} importantForAccessibility="no-hide-descendants"
          style={{ position: 'absolute', right: index === 3 ? '17%' : 8, top: index === 3 ? undefined : 8, bottom: index === 3 ? 10 : undefined, width: 32, height: 32, borderRadius: 16, borderWidth: 2, borderColor: c.text, backgroundColor: c.muted, opacity, transform: [{ scale }] }} />
      </View>
    </View>;
  })}</View>;
}
