import { isTauri } from '@tauri-apps/api/core';
import { getCurrentWindow } from '@tauri-apps/api/window';
export type DesktopMessage = {event: 'settings' | 'workflow'; state: Record<string, unknown>};
export interface ElectronBridge {
  call<T>(channel: 'settings' | 'workflow', method: string, args: unknown[]): Promise<T>;
  window(method: string, value?: boolean | {x: number; y: number; width: number; height: number}[]): Promise<boolean | void>;
  subscribe(listener: (message: DesktopMessage) => void): () => void;
  onWindow(listener: (event: string) => void): () => void;
  ready(): Promise<void>;
}
declare global { interface Window { clarifyDesktop?: ElectronBridge } }
export const electron = () => window.clarifyDesktop;
export const nativeWindow = () => !!electron() || isTauri();
export async function windowAction(method: 'minimize' | 'toggleMaximize' | 'isMaximized' | 'closeAccepted') {
  if (electron()) return electron()!.window(method);
  if (!isTauri()) return;
  if (method === 'closeAccepted') return getCurrentWindow().close();
  return getCurrentWindow()[method]();
}
