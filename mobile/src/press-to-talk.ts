export type RecordingAction = 'start' | 'lock' | 'finish' | 'cancel';

// Local gesture state stays synchronous while the native process accepts commands.
export class PressToTalk {
  private phase: 'idle' | 'held' | 'locked' = 'idle';
  private readonly send: (action: RecordingAction) => void;
  constructor(send: (action: RecordingAction) => void) { this.send = send; }

  press(enabled = true) {
    if (!enabled) return;
    if (this.phase === 'locked') {
      this.phase = 'idle';
      this.send('finish');
    } else if (this.phase === 'idle') {
      this.phase = 'held';
      this.send('start');
    }
  }
  move(verticalDistance: number) {
    if (this.phase === 'held' && verticalDistance <= -28) {
      this.phase = 'locked';
      this.send('lock');
    }
  }
  release() {
    if (this.phase === 'held') {
      this.phase = 'idle';
      this.send('finish');
    }
  }
  cancel() {
    if (this.phase !== 'idle') this.send('cancel');
    this.phase = 'idle';
  }
  cancelHeld() { if (this.phase === 'held') this.cancel(); }
  reset() { this.phase = 'idle'; }
}
