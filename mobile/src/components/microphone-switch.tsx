import { useRef, useState } from 'react';
import { router } from 'expo-router';
import { ActivityIndicator, Switch, Text, View } from 'react-native';
import Core from '../../modules/clarify-core';
import { t } from '../i18n';
import { isBusy, report, useClarify } from '../state/clarify';
import { Card, TextButton, ui, usePalette } from './ui';

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
  return <Card>
    <View style={[ui.row, { minHeight: 64 }]}>
      <View style={{ flex: 1, gap: 6 }}>
        <Text style={[ui.section, { color: c.text, marginTop: 0 }]}>Clarify</Text>
        <Text style={[ui.small, { color: c.muted }]}>{state.sessionActive ? t("Ligado") : t("Desligado")}</Text>
      </View>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 16, minHeight: 52 }}>
        <ActivityIndicator size="small" color={c.accent} animating={changing} style={{ opacity: changing ? 1 : 0 }} />
        <Switch accessibilityLabel={t("Ativar Clarify")} accessibilityState={{ busy: changing }} value={requested ?? state.sessionActive}
          disabled={blocked || !state.configured} onValueChange={value => void change(value)}
          style={{ transform: [{ scale: 1.25 }], marginHorizontal: 8 }} />
      </View>
    </View>
    {!state.configured && <TextButton disabled={blocked} onPress={() => router.navigate('/settings')}>{t("Configurar processamento")}</TextButton>}
  </Card>;
}
