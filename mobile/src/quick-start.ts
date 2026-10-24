export type GuideStep = 'keyboard' | 'microphone' | 'practice';
export interface GuideProgress {
  step: GuideStep;
  keyboardConfirmed: boolean;
  insertionConfirmed: boolean;
}
export type GuideAction = 'confirm-keyboard' | 'continue-microphone' | 'confirm-insertion' | 'back' | 'settings-returned';
export type GuideExit = 'confirmed' | 'later' | 'home';

export const initialGuide = (): GuideProgress => ({ step: 'keyboard', keyboardConfirmed: false, insertionConfirmed: false });

// Confirmations describe a user's checks, not detected iOS permission state.
export function guideTransition(progress: GuideProgress, action: GuideAction, microphoneActive: boolean): GuideProgress {
  if (action === 'confirm-keyboard' && progress.step === 'keyboard') {
    return { step: 'microphone', keyboardConfirmed: true, insertionConfirmed: false };
  }
  if (action === 'continue-microphone' && progress.step === 'microphone' && microphoneActive) {
    return { ...progress, step: 'practice', insertionConfirmed: false };
  }
  if (action === 'confirm-insertion' && progress.step === 'practice') {
    return { ...progress, insertionConfirmed: true };
  }
  if (action === 'back') {
    return { ...progress, step: progress.step === 'practice' ? 'microphone' : 'keyboard', insertionConfirmed: false };
  }
  return progress;
}

export function practiceResult(snapshot: { phase: string; operationID?: string; text?: string }, previousOperation?: string): string | null {
  if (snapshot.phase !== 'ready' || !snapshot.operationID || snapshot.operationID === previousOperation) return null;
  return snapshot.text?.trim() || null;
}

// Finishing preparation is separate from the manual insertion confirmation.
export function guideCompletion(progress: GuideProgress, exit: GuideExit): boolean | null {
  if (exit !== 'confirmed') return false;
  return guideTransition(progress, 'confirm-insertion', false).insertionConfirmed ? true : null;
}
