import { NativeTabs } from 'expo-router/unstable-native-tabs';

export default function TabsLayout() {
  return <NativeTabs>
    <NativeTabs.Trigger name="index"><NativeTabs.Trigger.Label>Home</NativeTabs.Trigger.Label><NativeTabs.Trigger.Icon sf={{ default: 'house', selected: 'house.fill' }} /></NativeTabs.Trigger>
    <NativeTabs.Trigger name="dictionary"><NativeTabs.Trigger.Label>Dicionário</NativeTabs.Trigger.Label><NativeTabs.Trigger.Icon sf={{ default: 'book', selected: 'book.fill' }} /></NativeTabs.Trigger>
    <NativeTabs.Trigger name="account"><NativeTabs.Trigger.Label>Conta</NativeTabs.Trigger.Label><NativeTabs.Trigger.Icon sf={{ default: 'person.crop.circle', selected: 'person.crop.circle.fill' }} /></NativeTabs.Trigger>
  </NativeTabs>;
}
