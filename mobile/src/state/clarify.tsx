import { t } from "../i18n";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { Alert, AppState } from 'react-native';
import Core, { type Snapshot, type AccountSnapshot } from '../../modules/clarify-core';
import { activateMicrophone } from './activation';
import { errorMessage } from '../errors';

const idle: Snapshot = { sessionActive: false, heartbeat: 0, phase: 'idle', configured: false };
export const isBusy = (state: Snapshot) => ['recording', 'locked', 'transcribing', 'rewriting'].includes(state.phase);
export function report(error: unknown) {
  Alert.alert('Clarify', t(errorMessage(error)));
}

function useClarifyState() {
  const [state, setState] = useState(idle);
  const [account, setAccount] = useState<AccountSnapshot>();
  const [accountBusy, setAccountBusy] = useState(false);
  const [onboardingRequired, setOnboardingRequired] = useState<boolean | null>(null);
  const [setupError, setSetupError] = useState(false);
  const mounted = useRef(true);
  const accountRequest = useRef(0);
  const setupRequest = useRef(0);
  const presentation = useRef<Promise<void> | null>(null);
  const markOnboardingPresented = useCallback(() => {
    if (!presentation.current) {
      presentation.current = Core.markOnboardingPresented().catch(error => {
        presentation.current = null;
        throw error;
      });
    }
    return presentation.current;
  }, []);
  const refreshOnboarding = useCallback(async () => {
    const request = ++setupRequest.current;
    try {
      const required = await Core.onboardingRequired();
      if (mounted.current && request === setupRequest.current) { setOnboardingRequired(required); setSetupError(false); }
    } catch { if (mounted.current && request === setupRequest.current) setSetupError(true); }
  }, []);
  const dismissOnboarding = useCallback(async () => {
    await markOnboardingPresented();
    ++setupRequest.current;
    if (mounted.current) setOnboardingRequired(false);
  }, [markOnboardingPresented]);
  const completeOnboarding = useCallback(async () => {
    const request = ++setupRequest.current;
    await Core.completeOnboarding();
    if (mounted.current && request === setupRequest.current) setOnboardingRequired(false);
  }, []);
  // Presentation is read once per app launch. Account changes do not restart it.
  useEffect(() => {
    let active = true;
    const request = ++setupRequest.current;
    void Core.onboardingRequired().then(required => {
      if (active && request === setupRequest.current) { setOnboardingRequired(required); setSetupError(false); }
    }).catch(() => { if (active && request === setupRequest.current) setSetupError(true); });
    return () => { active = false; };
  }, []);
  const refreshAccount = useCallback(async () => {
    const request = ++accountRequest.current;
    const value = await Core.getAccount();
    if (mounted.current && request === accountRequest.current) setAccount(value);
    return value;
  }, []);
  const accountCommand = useCallback(async (action: string, value = '') => {
    const request = ++accountRequest.current;
    setAccountBusy(true);
    try {
      const next = await Core.accountCommand(action, value);
      if (mounted.current && request === accountRequest.current) setAccount(next);
    }
    finally { setAccountBusy(false); await refreshAccount(); }
  }, [refreshAccount]);
  // Native snapshots are local reads. Server refresh has its own one-minute gate.
  useEffect(() => {
    let live = true;
    let pending = false;
    const sync = async () => {
      if (pending || AppState.currentState !== 'active') return;
      pending = true;
      const request = ++accountRequest.current;
      try { const next = await Core.accountCommand('auto', ''); if (live && request === accountRequest.current) setAccount(next); }
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
    const request = ++accountRequest.current;
    void Core.getAccount().then(value => { if (active && request === accountRequest.current) setAccount(value); }).catch(report);
    return () => { active = false; };
  }, [state.libraryRevision, state.configured]);
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
    onboardingRequired, setupError, refreshOnboarding, markOnboardingPresented, dismissOnboarding, completeOnboarding };
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
