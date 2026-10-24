import { t } from "../../i18n";
import { usePalette } from '../../components/ui';
import { NativeTabs } from 'expo-router/unstable-native-tabs';

export default function TabsLayout() {
  const c = usePalette();
  return <NativeTabs tintColor={c.text}>
    <NativeTabs.Trigger name="index"><NativeTabs.Trigger.Label>{t("Início")}</NativeTabs.Trigger.Label><NativeTabs.Trigger.Icon sf={{ default: 'house', selected: 'house.fill' }} /></NativeTabs.Trigger>
    <NativeTabs.Trigger name="dictionary"><NativeTabs.Trigger.Label>{t("Dicionário")}</NativeTabs.Trigger.Label><NativeTabs.Trigger.Icon sf={{ default: 'book', selected: 'book.fill' }} /></NativeTabs.Trigger>
    <NativeTabs.Trigger name="snippets"><NativeTabs.Trigger.Label>{t("Snippets")}</NativeTabs.Trigger.Label><NativeTabs.Trigger.Icon sf={{ default: 'text.quote', selected: 'text.quote' }} /></NativeTabs.Trigger>
  </NativeTabs>;
}
