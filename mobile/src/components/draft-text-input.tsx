import { useState, type Ref } from 'react';
import { TextInput, type TextInputProps } from 'react-native';

type DraftTextInputProps = Omit<TextInputProps, 'value' | 'defaultValue'> & {
  initialValue: string;
  inputRef?: Ref<TextInput>;
};

export function DraftTextInput({ initialValue, inputRef, ...props }: DraftTextInputProps) {
  // Native owns edits. Snapshot renders must not write an earlier JS draft back.
  // Callers own deliberate clears through inputRef and new drafts through remounts.
  const [initialText] = useState(initialValue);
  return <TextInput {...props} ref={inputRef} defaultValue={initialText} />;
}
