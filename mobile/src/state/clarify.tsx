import { t } from "../i18n";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { Alert, AppState } from 'react-native';
import Core, { type Snapshot, type AccountSnapshot } from '../../modules/clarify-core';
import { activateMicrophone } from './activation';

const idle: Snapshot = { sessionActive: false, heartbeat: 0, phase: 'idle', configured: false };
export const isBusy = (state: Snapshot) => ['recording', 'locked', 'transcribing', 'rewriting'].includes(state.phase);
export function report(error: unknown) {
  Alert.alert('Clarify', error instanceof Error ? t(error.message) : t("Não foi possível concluir. Tente novamente."));
}

function useClarifyState() {
  const [state, setState] = useState(idle);
  const [account, setAccount] = useState<AccountSnapshot>();
  const [accountBusy, setAccountBusy] = useState(false);
  const [onboardingRequired, setOnboardingRequired] = useState<boolean | null>(null);
  const [setupError, setSetupError] = useState(false);
  const refreshOnboarding = useCallback(async () => {
    try { setOnboardingRequired(await Core.onboardingRequired()); setSetupError(false); }
    catch { setSetupError(true); }
  }, []);
  const completeOnboarding = useCallback(async (mode: 'account' | 'byok') => {
    await Core.completeOnboarding(mode);
    setOnboardingRequired(false);
  }, []);
  useEffect(() => {
    let active = true;
    void Core.onboardingRequired().then(value => { if (active) setOnboardingRequired(value); })
      .catch(() => { if (active) setSetupError(true); });
    return () => { active = false; };
  }, []);
  const refreshAccount = useCallback(async () => { const value = await Core.getAccount(); setAccount(value); return value; }, []);
  const accountCommand = useCallback(async (action: string, value = '') => {
    setAccountBusy(true);
    try { setAccount(await Core.accountCommand(action, value)); }
    finally { setAccountBusy(false); await refreshAccount(); }
  }, [refreshAccount]);
  // Native snapshots are local reads. Server refresh has its own one-minute gate.
  useEffect(() => {
    let live = true;
    let pending = false;
    const sync = async () => {
      if (pending || AppState.currentState !== 'active') return;
      pending = true;
      try { const next = await Core.accountCommand('auto', ''); if (live) setAccount(next); }
      catch { /* Keep cached data during temporary offline periods. */ }
      finally { pending = false; }
    };
    void sync();
    const timer = setInterval(() => void sync(), 60000);
    const listener = AppState.addEventListener('change', value => { if (value === 'active') void sync(); });
    return () => { live = false; clearInterval(timer); listener.remove(); };
  }, []);
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
    request.current = activateMicrophone(Core, token).then((next) => {
      if (mounted.current) setState(next);
    }).catch(async (error: unknown) => {
      // Show the native failure in the page and keyboard as well as the alert.
      await refresh().catch(() => undefined);
      throw error;
    }).finally(() => {
      request.current = null;
      if (mounted.current) setActivating(false);
    });
    return request.current;
  }, [refresh]);
  useEffect(() => {
    let active = true;
    void Core.getAccount().then(value => { if (active) setAccount(value); }).catch(report);
    return () => { active = false; };
  }, [state.libraryRevision]);
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
  return { state, refresh, activate, activating, keyboardEntry, setKeyboardEntry, keyboardToken, setKeyboardToken,
    account, accountBusy, refreshAccount, accountCommand,
    onboardingRequired, setupError, refreshOnboarding, completeOnboarding };
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
