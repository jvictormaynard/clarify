import { View } from 'react-native';
import { usePalette } from './ui';

// Geometry from assets/icon.svg. Draw only the mark, with no icon background.
const bars = [
  [197.594, 438.424, 71.301, 141.084], [337.161, 232.865, 70.542, 345.126],
  [337.161, 649.292, 70.542, 142.601], [475.970, 163.840, 70.542, 140.326],
  [475.970, 337.541, 70.542, 347.401], [475.970, 713.766, 70.542, 146.394],
  [615.538, 232.865, 70.542, 143.360], [615.538, 438.424, 70.542, 353.470],
  [755.105, 439.182, 71.301, 141.084],
];

export function ClarifyLogo({ size = 64 }: { size?: number }) {
  const c = usePalette();
  const scale = size / 764;
  return <View accessible={false} importantForAccessibility="no-hide-descendants" style={{ width: size, height: size }}>
    {bars.map(([x, y, width, height], index) => <View key={index} style={{
      position: 'absolute', left: (x - 160) * scale + (size - 704 * scale) / 2,
      top: (y - 130) * scale, width: width * scale, height: height * scale,
      borderRadius: width * scale / 2, backgroundColor: c.text,
    }} />)}
  </View>;
}
