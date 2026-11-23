export type DesktopMessage = {event: 'settings' | 'workflow' | 'meetings' | 'meeting-status'; state: Record<string, unknown>};
type PermissionGuideRequest = {permission: 'accessibility' | 'shortcuts'; locale: string};
export interface ElectronBridge {
  separateMeetingWindow?: boolean;
  dragInstalledApp?(): void;
  call<T>(channel: 'settings' | 'workflow' | 'meetings', method: string, args: unknown[]): Promise<T>;
  window(method: string, value?: boolean | string | PermissionGuideRequest | {x: number; y: number; width: number; height: number}[]): Promise<boolean | void>;
  subscribe(listener: (message: DesktopMessage) => void): () => void;
  onWindow(listener: (event: string, value?: string) => void): () => void;
  ready(): Promise<void>;
}
declare global { interface Window { clarifyDesktop?: ElectronBridge } }
export const electron = () => window.clarifyDesktop;
export const nativeWindow = () => !!electron();
export async function windowAction(method: 'minimize' | 'toggleMaximize' | 'isMaximized' | 'closeAccepted') {
  if (electron()) return electron()!.window(method);
}

export const isMacDesktop = () => nativeWindow() && navigator.userAgent.includes("Macintosh");

export function shortcutKey(event: Pick<KeyboardEvent, "key" | "code">) {
  // On macOS Option can produce a character or dead key instead of a letter.
  const physicalKey = isMacDesktop() && /^(?:Key[A-Z]|Digit[0-9])$/.test(event.code);
  if (physicalKey) return event.code.slice(-1);
  return event.key === " " ? "SPACE" : event.key.toUpperCase();
}
