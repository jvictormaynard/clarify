export type GuideStep = 'keyboard' | 'microphone' | 'practice';
export interface GuideProgress {
  step: GuideStep;
  keyboardConfirmed: boolean;
}
export type GuideAction = 'confirm-keyboard' | 'continue-microphone' | 'back' | 'settings-returned';
export type GuideExit = 'confirmed' | 'later';

export const initialGuide = (): GuideProgress => ({ step: 'keyboard', keyboardConfirmed: false });

// Confirmations describe a user's checks, not detected iOS permission state.
export function guideTransition(progress: GuideProgress, action: GuideAction, microphoneActive: boolean): GuideProgress {
  if (action === 'confirm-keyboard' && progress.step === 'keyboard') {
    return { step: 'microphone', keyboardConfirmed: true };
  }
  if (action === 'continue-microphone' && progress.step === 'microphone' && microphoneActive) {
    return { ...progress, step: 'practice' };
  }
  if (action === 'back') {
    return { ...progress, step: progress.step === 'practice' ? 'microphone' : 'keyboard' };
  }
  return progress;
}

// Only the current practice input can unlock completion; native snapshots are not evidence of insertion.
export function guideCompletion(progress: GuideProgress, exit: GuideExit, practiceText: string): boolean | null {
  if (exit !== 'confirmed') return false;
  return progress.step === 'practice' && practiceText.trim() ? true : null;
}
