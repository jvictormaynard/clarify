import { useState, type ReactNode } from 'react';
import { router } from 'expo-router';
import { Modal, Pressable, ScrollView, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { SymbolView } from 'expo-symbols';
import { useClarify } from '../state/clarify';
import { t } from '../i18n';
import { ClarifyLogo } from './clarify-logo';
import { Divider, NavigationRow, ui, usePalette, useReducedMotion } from './ui';

export function WorkspaceHeader({ title, accessory }: { title: string; accessory?: ReactNode }) {
  const c = usePalette();
  const reduced = useReducedMotion();
  const { account } = useClarify();
  const [open, setOpen] = useState(false);
  function navigate(path: '/account' | '/settings' | '/processing' | '/guide' | '/text-actions') {
    setOpen(false); router.push(path);
  }
  return <>
    <View style={{ minHeight: 48, paddingHorizontal: 12, flexDirection: 'row', alignItems: 'center', gap: 8 }}>
      <Pressable testID="workspace.menu" accessibilityRole="button" accessibilityLabel={t('Abrir menu')} accessibilityState={{ expanded: open }} onPress={() => setOpen(true)}
        style={({ pressed }) => ({ width: 44, height: 44, alignItems: 'center', justifyContent: 'center', opacity: pressed ? 0.6 : 1 })}>
        <SymbolView name="line.3.horizontal" size={21} tintColor={c.text} accessible={false} />
      </Pressable>
      <View style={{ flex: 1, flexDirection: 'row', gap: 8, alignItems: 'center', justifyContent: 'center' }}>
        {title === 'Clarify' && <ClarifyLogo size={22} />}
        <Text accessibilityRole="header" style={{ fontSize: 17, fontWeight: '500', color: c.text }}>{title}</Text>
      </View>
      <View style={{ minWidth: 44, alignItems: 'center' }}>{accessory}</View>
    </View>
    <Modal visible={open} transparent animationType={reduced ? 'none' : 'fade'} onRequestClose={() => setOpen(false)}>
      <View style={{ flex: 1, flexDirection: 'row', backgroundColor: '#00000066' }}>
        <SafeAreaView accessibilityViewIsModal style={{ width: '86%', maxWidth: 360, backgroundColor: c.background }}>
          <ScrollView contentContainerStyle={{ padding: 20, gap: 24, flexGrow: 1 }}>
            <View style={ui.row}>
              <ClarifyLogo size={28} />
              <Pressable accessibilityRole="button" accessibilityLabel={t('Fechar')} onPress={() => setOpen(false)} style={{ width: 44, height: 44, alignItems: 'center', justifyContent: 'center' }}>
                <SymbolView name="xmark" size={20} tintColor={c.text} accessible={false} />
              </Pressable>
            </View>
            <View style={{ gap: 8 }}><Text style={[ui.section, { color: c.text }]}>{t('Conta Clarify')}</Text>
              <Text style={[ui.small, { color: c.muted }]}>{account?.signedIn ? account.email : t('Meu computador')}</Text></View>
            <Divider />
            <NavigationRow testID="menu.actions" title={t('Gerenciar ações')} icon="wand.and.stars" onPress={() => navigate('/text-actions')} />
            <NavigationRow testID="menu.processing" title={t('Processamento')} icon="desktopcomputer" onPress={() => navigate('/processing')} />
            <View style={{ flex: 1 }} />
            <NavigationRow testID="menu.guide" title={t('Como usar')} icon="questionmark.circle" onPress={() => navigate('/guide')} />
            <Divider />
            <NavigationRow testID="menu.settings" title={t('Ajustes')} icon="gearshape" onPress={() => navigate('/settings')} />
            <NavigationRow testID="menu.account" title={t('Conta')} icon="person.crop.circle" onPress={() => navigate('/account')} />
          </ScrollView>
        </SafeAreaView>
        <Pressable accessibilityRole="button" accessibilityLabel={t('Fechar')} onPress={() => setOpen(false)} style={{ flex: 1 }} />
      </View>
    </Modal>
  </>;
}
