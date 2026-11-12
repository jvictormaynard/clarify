import { useRef, useState } from 'react';
import { router } from 'expo-router';
import { ActivityIndicator, Switch, Text, View } from 'react-native';
import Core from '../../modules/clarify-core';
import { t } from '../i18n';
import { isBusy, report, useClarify } from '../state/clarify';
import { Card, ui, usePalette } from './ui';

export function MicrophoneSwitch() {
  const c = usePalette();
  const { state, account, accountBusy, activate, activating, refresh } = useClarify();
  const pending = useRef(false);
  const [requested, setRequested] = useState<boolean | null>(null);
  const changing = requested !== null || activating;
  const blocked = changing || accountBusy || !!account?.busy || (!state.sessionActive && isBusy(state));
  async function change(enabled: boolean) {
    if (pending.current || blocked || enabled === state.sessionActive) return;
    if (enabled && !state.configured) { router.navigate('/settings'); return; }
    pending.current = true; setRequested(enabled);
    try {
      if (enabled) await activate();
      else { await Core.deactivate(); await refresh(); }
    } catch (error) { report(error); }
    finally { pending.current = false; setRequested(null); }
  }
  const enabled = requested ?? state.sessionActive;
  return <Card style={{ paddingVertical: 12 }}>
    <View style={{ minHeight: 56, flexDirection: 'row', alignItems: 'center', gap: 16 }}>
      <View style={{ flex: 1, gap: 4 }}>
        <Text style={[ui.body, { fontWeight: '600', color: c.text }]}>{t('Ativar Clarify')}</Text>
        <Text accessibilityLiveRegion="polite" style={[ui.small, { color: c.muted }]}>{enabled ? t('Microfone ativo') : t('Microfone desativado')}</Text>
      </View>
      <Switch accessibilityLabel={t("Ativar Clarify")} accessibilityState={{ busy: changing }} value={enabled}
        disabled={blocked} onValueChange={value => void change(value)}
        style={{ alignSelf: 'center', marginHorizontal: 8 }} />
      {changing && <ActivityIndicator size="small" color={c.accent} style={{ marginLeft: 4 }} />}
    </View>
  </Card>;
}
