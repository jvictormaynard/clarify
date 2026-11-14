import { t } from "../../i18n";
import { usePalette } from '../../components/ui';
import { NativeTabs } from 'expo-router/unstable-native-tabs';

export default function TabsLayout() {
  const c = usePalette();
  return <NativeTabs tintColor={c.text}>
    <NativeTabs.Trigger name="index"><NativeTabs.Trigger.Label>{t("Início")}</NativeTabs.Trigger.Label><NativeTabs.Trigger.Icon sf={{ default: 'house', selected: 'house.fill' }} /></NativeTabs.Trigger>
    <NativeTabs.Trigger name="words"><NativeTabs.Trigger.Label>{t("Dicionário")}</NativeTabs.Trigger.Label><NativeTabs.Trigger.Icon sf="book" /></NativeTabs.Trigger>
    <NativeTabs.Trigger name="phrases"><NativeTabs.Trigger.Label>{t("Snippets")}</NativeTabs.Trigger.Label><NativeTabs.Trigger.Icon sf="text.quote" /></NativeTabs.Trigger>
    <NativeTabs.Trigger name="style"><NativeTabs.Trigger.Label>{t("Estilo")}</NativeTabs.Trigger.Label><NativeTabs.Trigger.Icon sf="textformat" /></NativeTabs.Trigger>
    <NativeTabs.Trigger name="actions"><NativeTabs.Trigger.Label>{t("Ações")}</NativeTabs.Trigger.Label><NativeTabs.Trigger.Icon sf="wand.and.stars" /></NativeTabs.Trigger>
    <NativeTabs.Trigger name="library" hidden />
    <NativeTabs.Trigger name="preferences" hidden />
  </NativeTabs>;
}
