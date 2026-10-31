import { useEffect, useState, type Ref } from 'react';
import { TextInput, type TextInputProps } from 'react-native';

type DraftTextInputProps = Omit<TextInputProps, 'value' | 'defaultValue'> & {
  initialValue: string;
  inputRef?: Ref<TextInput>;
};

const traceInput = process.env.EXPO_PUBLIC_CLARIFY_INPUT_TRACE === '1';

export function DraftTextInput({ initialValue, inputRef, ...props }: DraftTextInputProps) {
  // Native owns edits. Snapshot renders must not write an earlier JS draft back.
  // Callers own deliberate clears through inputRef and new drafts through remounts.
  const [initialText] = useState(initialValue);
  const [name] = useState(props.testID ?? props.accessibilityLabel ?? 'unnamed');
  useEffect(() => {
    if (!traceInput) return;
    console.info('CLARIFY_INPUT_JS', JSON.stringify({ time: Date.now() / 1000, event: 'mount', name, initialText }));
    return () => console.info('CLARIFY_INPUT_JS', JSON.stringify({ time: Date.now() / 1000, event: 'unmount', name }));
  }, [name, initialText]);
  useEffect(() => {
    if (traceInput) console.info('CLARIFY_INPUT_JS', JSON.stringify({ time: Date.now() / 1000, event: 'editable', name, editable: props.editable ?? true }));
  }, [name, props.editable]);
  return <TextInput {...props} ref={inputRef} defaultValue={initialText} onChange={traceInput ? event => {
    console.info('CLARIFY_INPUT_JS', JSON.stringify({ time: Date.now() / 1000, event: 'change', name, text: event.nativeEvent.text, count: event.nativeEvent.eventCount }));
    props.onChange?.(event);
  } : props.onChange} />;
}
