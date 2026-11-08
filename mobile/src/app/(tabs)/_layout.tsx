import { t } from "../../i18n";
import { usePalette } from '../../components/ui';
import { NativeTabs } from 'expo-router/unstable-native-tabs';

export default function TabsLayout() {
  const c = usePalette();
  return <NativeTabs tintColor={c.text}>
    <NativeTabs.Trigger name="index"><NativeTabs.Trigger.Label>{t("Ditado")}</NativeTabs.Trigger.Label><NativeTabs.Trigger.Icon sf={{ default: 'mic', selected: 'mic.fill' }} /></NativeTabs.Trigger>
    <NativeTabs.Trigger name="actions"><NativeTabs.Trigger.Label>{t("Ações")}</NativeTabs.Trigger.Label><NativeTabs.Trigger.Icon sf="wand.and.stars" /></NativeTabs.Trigger>
    <NativeTabs.Trigger name="library"><NativeTabs.Trigger.Label>{t("Biblioteca")}</NativeTabs.Trigger.Label><NativeTabs.Trigger.Icon sf={{ default: 'books.vertical', selected: 'books.vertical.fill' }} /></NativeTabs.Trigger>
    <NativeTabs.Trigger name="preferences"><NativeTabs.Trigger.Label>{t("Ajustes")}</NativeTabs.Trigger.Label><NativeTabs.Trigger.Icon sf="gearshape" /></NativeTabs.Trigger>
  </NativeTabs>;
}
