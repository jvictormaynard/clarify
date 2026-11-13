import type { ReactNode } from 'react';
import { ImageBackground, Text, View } from 'react-native';
import { ButtonSurface, ui } from './ui';

const landscapes = {
  dictionary: require('../../assets/guides/guide-dictionary-landscape.webp'),
  snippets: require('../../assets/guides/guide-snippets-landscape.webp'),
  actions: require('../../assets/guides/guide-actions-landscape.webp'),
};

// Repository-owned desktop landscapes, bundled locally for offline iOS use.
export function NatureCard({ kind, title, detail, children }: { kind: keyof typeof landscapes; title: string; detail: string; children?: ReactNode }) {
  return <View style={{ borderRadius: 12, overflow: 'hidden' }}>
    <ImageBackground source={landscapes[kind]} resizeMode="cover">
      <View style={{ backgroundColor: kind === 'snippets' ? '#2a140999' : '#07171d99', padding: 24, gap: 12 }}>
        <Text accessibilityRole="header" style={{ fontSize: 23, lineHeight: 29, letterSpacing: -0.6, fontWeight: '500', color: '#ffffff' }}>{title}</Text>
        <Text style={[ui.body, { color: '#f5f5f5' }]}>{detail}</Text>
        <ButtonSurface.Provider value="image">{children}</ButtonSurface.Provider>
      </View>
    </ImageBackground>
  </View>;
}
