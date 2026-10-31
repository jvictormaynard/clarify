import { forwardRef, useState } from 'react';
import { TextInput, type TextInputProps } from 'react-native';

type DraftInputProps = Omit<TextInputProps, 'value' | 'defaultValue'> & { initialValue: string };

// Keep typing in the native field. A new mount restores its initial value;
// callers use the native ref to clear a field that remains mounted.
export const DraftInput = forwardRef<TextInput, DraftInputProps>(function DraftInput({ initialValue, ...props }, ref) {
  const [seed] = useState(initialValue);
  return <TextInput {...props} ref={ref} defaultValue={seed} />;
});
