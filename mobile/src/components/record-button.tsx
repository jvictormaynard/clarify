import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, PanResponder, Pressable, StyleSheet, Text, View, type PanResponderInstance } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import Core from '../../modules/clarify-core';
import { PressToTalk, type RecordingAction } from '../press-to-talk';
import { report, useClarify } from '../state/clarify';
import { usePalette } from './ui';

export function RecordButton() {
  const { state } = useClarify();
  const c = usePalette();
  const latest = useRef(state);
  useLayoutEffect(() => { latest.current = state; }, [state]);
  const [held, setHeld] = useState(false);
  const [localLocked, setLocalLocked] = useState(false);
  const operation = useRef('');
  const chain = useRef(Promise.resolve());
  const send = useCallback((action: RecordingAction) => {
    if (action === 'start') operation.current = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const id = operation.current;
    setHeld(action === 'start'); setLocalLocked(action === 'lock');
    chain.current = chain.current.then(() => Core.command(action, id)).catch(report);
  }, []);
  const control = useRef<PressToTalk | null>(null);
  const [gesture, setGesture] = useState<PanResponderInstance | null>(null);
  const accessibleRecord = () => {
    if (!latest.current.sessionActive || ['transcribing', 'rewriting'].includes(latest.current.phase)) return;
    if (['recording', 'locked'].includes(latest.current.phase)) {
      operation.current = latest.current.operationID ?? operation.current;
      control.current?.reset(); send('finish');
    } else { control.current?.press(); control.current?.move(-28); control.current?.release(); }
  };
  useLayoutEffect(() => {
    const instance = new PressToTalk(send);
    control.current = instance;
    setGesture(PanResponder.create({
    onStartShouldSetPanResponder: () => latest.current.sessionActive && !['transcribing', 'rewriting'].includes(latest.current.phase),
    onPanResponderGrant: () => {
      if (latest.current.phase === 'locked' || (latest.current.phase === 'recording' && latest.current.operationID !== operation.current)) {
        operation.current = latest.current.operationID ?? operation.current;
        instance.reset(); send('finish');
      } else instance.press();
    },
    onPanResponderMove: (_, move) => instance.move(move.dy),
    onPanResponderRelease: () => instance.release(),
    onPanResponderTerminate: () => instance.cancelHeld(), onPanResponderTerminationRequest: () => false,
    }));
    return () => {
      instance.cancelHeld();
      control.current = null;
    };
  }, [send]);
  useFocusEffect(useCallback(() => () => control.current?.cancelHeld(), []));
  useEffect(() => {
    if (!['recording', 'locked'].includes(state.phase) && state.operationID === operation.current) {
      control.current?.reset(); setHeld(false); setLocalLocked(false);
    }
  }, [state.phase, state.operationID]);
  const hint = held && !localLocked && state.phase !== 'locked';
  const [animation] = useState(() => new Animated.Value(0));
  useEffect(() => {
    let active = true;
    void AccessibilityInfo.isReduceMotionEnabled().then((reduce) => {
      if (active) Animated.timing(animation, { toValue: hint ? 1 : 0, duration: reduce ? 0 : 180, useNativeDriver: true }).start();
    });
    return () => { active = false; };
  }, [hint, animation]);
  const locked = state.phase === 'locked' || localLocked;
  const busy = ['transcribing', 'rewriting'].includes(state.phase);
  return <View style={styles.wrap}>
    <View {...gesture?.panHandlers} accessible accessibilityRole="button" accessibilityLabel={locked ? 'Finalizar gravação' : 'Gravar'}
      accessibilityState={{ disabled: !state.sessionActive || busy }} accessibilityHint="Segure para falar. Deslize para cima para travar."
      accessibilityActions={[{ name: 'activate', label: 'Gravar ou finalizar' }]} onAccessibilityAction={accessibleRecord}
      style={[styles.button, { backgroundColor: c.text, opacity: state.sessionActive && !busy ? 1 : 0.35 }]}>
      <Animated.View pointerEvents="none" style={[styles.tips, { opacity: animation }]}>
        {[0, 1].map((i) => <View key={i} style={[styles.chevron, { borderColor: c.background }]} />)}
      </Animated.View>
      {locked ? <SymbolView name="paperplane.fill" size={30} tintColor={c.background} pointerEvents="none" /> :
        <Animated.View pointerEvents="none" style={[styles.micDrawing, { transform: [{ translateY: animation.interpolate({ inputRange: [0, 1], outputRange: [0, 9] }) }, { scale: animation.interpolate({ inputRange: [0, 1], outputRange: [1, 0.78] }) }] }]}>
          <View style={[styles.capsule, { backgroundColor: c.background }]} /><View style={[styles.arc, { borderColor: c.background }]} /><View style={[styles.stem, { backgroundColor: c.background }]} />
        </Animated.View>}
    </View>
    {['recording', 'locked', 'transcribing', 'rewriting'].includes(state.phase) && <Pressable accessibilityRole="button" hitSlop={10} onPress={() => {
      operation.current = latest.current.operationID ?? operation.current;
      control.current?.reset(); send('cancel');
    }}><Text style={{ color: c.muted, padding: 8 }}>Cancelar</Text></Pressable>}
  </View>;
}
const styles = StyleSheet.create({
  wrap: { alignItems: 'center', gap: 4 }, button: { width: 88, height: 88, borderRadius: 44, alignItems: 'center', justifyContent: 'center' },
  tips: { position: 'absolute', top: 13, gap: 1, alignItems: 'center' }, chevron: { width: 9, height: 9, borderTopWidth: 1.5, borderLeftWidth: 1.5, transform: [{ rotate: '45deg' }] },
  micDrawing: { width: 32, height: 42, alignItems: 'center' }, capsule: { width: 14, height: 27, borderRadius: 8 },
  arc: { width: 28, height: 23, borderWidth: 2, borderTopWidth: 0, borderBottomLeftRadius: 16, borderBottomRightRadius: 16, marginTop: -16 }, stem: { width: 2, height: 8 },
});
