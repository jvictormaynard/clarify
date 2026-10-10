import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { Alert, AppState } from 'react-native';
import Core, { type Snapshot } from '../../modules/clarify-core';

const idle: Snapshot = { sessionActive: false, heartbeat: 0, phase: 'idle', configured: false };
export const isBusy = (state: Snapshot) => ['recording', 'locked', 'transcribing', 'rewriting'].includes(state.phase);
export function report(error: unknown) {
  Alert.alert('Clarify', error instanceof Error ? error.message : 'Não foi possível concluir. Tente novamente.');
}

function useClarifyState() {
  const [state, setState] = useState(idle);
  const [activating, setActivating] = useState(false);
  const [keyboardEntry, setKeyboardEntry] = useState(false);
  const [keyboardToken, setKeyboardToken] = useState<string | undefined>();
  const request = useRef<Promise<void> | null>(null);
  const mounted = useRef(true);
  const refresh = useCallback(async () => {
    const next = await Core.getSnapshot();
    if (mounted.current) setState(next);
    return next;
  }, []);
  const activate = useCallback((token?: string) => {
    if (request.current) return request.current;
    setActivating(true);
    request.current = Core.activate().then(() => refresh()).then(async () => {
      if (token) await Core.returnToSource(token);
    }).finally(() => {
      request.current = null;
      if (mounted.current) setActivating(false);
    });
    return request.current;
  }, [refresh]);
  useEffect(() => {
    mounted.current = true;
    let pending = false;
    let reported = false;
    const poll = async () => {
      if (pending || AppState.currentState !== 'active') return;
      pending = true;
      try { await refresh(); reported = false; }
      catch (error) { if (!reported && mounted.current) { reported = true; report(error); } }
      finally { pending = false; }
    };
    void poll();
    const timer = setInterval(() => void poll(), 250);
    const listener = AppState.addEventListener('change', (value) => {
      if (value === 'active') void poll();
      if (value === 'background') { setKeyboardEntry(false); setKeyboardToken(undefined); }
    });
    return () => { mounted.current = false; clearInterval(timer); listener.remove(); };
  }, [refresh]);
  return { state, refresh, activate, activating, keyboardEntry, setKeyboardEntry, keyboardToken, setKeyboardToken };
}
const Context = createContext<ReturnType<typeof useClarifyState> | null>(null);
export function ClarifyProvider({ children }: { children: ReactNode }) {
  return <Context value={useClarifyState()}>{children}</Context>;
}
export function useClarify() {
  const value = useContext(Context);
  if (!value) throw new Error('ClarifyProvider ausente.');
  return value;
}
