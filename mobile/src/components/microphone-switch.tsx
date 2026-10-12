import { useRef, useState } from 'react';
import { router } from 'expo-router';
import { ActivityIndicator, Switch, Text, View } from 'react-native';
import Core from '../../modules/clarify-core';
import { t } from '../i18n';
import { isBusy, report, useClarify } from '../state/clarify';
import { Card, usePalette } from './ui';

export function MicrophoneSwitch() {
  const c = usePalette();
  const { state, account, accountBusy, activate, activating, refresh } = useClarify();
  const pending = useRef(false);
  const [requested, setRequested] = useState<boolean | null>(null);
  const changing = requested !== null || activating;
  const blocked = changing || accountBusy || !!account?.busy || (!state.sessionActive && isBusy(state));
  async function change(enabled: boolean) {
    if (pending.current || blocked || enabled === state.sessionActive) return;
    if (!state.configured) { router.navigate('/settings'); return; }
    pending.current = true; setRequested(enabled);
    try {
      if (enabled) await activate();
      else { await Core.deactivate(); await refresh(); }
    } catch (error) { report(error); }
    finally { pending.current = false; setRequested(null); }
  }
  const enabled = requested ?? state.sessionActive;
  return <Card style={{ paddingVertical: 12 }}>
    <View style={{ minHeight: 56, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 16 }}>
      <Text style={{ width: 44, textAlign: 'right', fontSize: 16, fontWeight: enabled ? '400' : '600', color: enabled ? c.muted : c.text }}>Off</Text>
      <Switch accessibilityLabel={t("Ativar Clarify")} accessibilityState={{ busy: changing }} value={enabled}
        disabled={blocked} onValueChange={value => void change(value)}
        style={{ transform: [{ scale: 1.25 }], marginHorizontal: 8 }} />
      <Text style={{ width: 44, fontSize: 16, fontWeight: enabled ? '600' : '400', color: enabled ? c.text : c.muted }}>On</Text>
      {changing && <ActivityIndicator size="small" color={c.accent} style={{ position: 'absolute', right: 0 }} />}
    </View>
  </Card>;
}
