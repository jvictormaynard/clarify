import { useDockPresentation } from './use-dock-presentation';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Check, Copy, FileAudio, LoaderCircle, Mic, RotateCcw, Settings, Square, X, ClipboardPaste, Sparkles, ChevronRight } from 'lucide-react';
import { LanguageMark } from './components/language-mark';
import { electron } from './platform';
import { setUiLanguage } from './i18n';
import { pillText as t } from './pill-labels';
import './styles/pill.css';
import type { WritingStyle } from './settings/bridge';

/** One frame-rate envelope owns motion; unscaled radii keep quiet bars rounded. */
function CaptureWave({level, active}: {level: number; active: boolean}) {
  const bars = useRef<HTMLDivElement>(null);
  const latest = useRef(level);
  latest.current = level;
  useEffect(() => {
    if (!active) return;
    const motion = matchMedia('(prefers-reduced-motion: reduce)');
    let frame = 0;
    const start = performance.now();
    let previous = start;
    let smoothed = 0;
    let heldLevel = 0;
    const draw = (now: number) => {
      const elapsed = Math.min(64, Math.max(0, now - previous));
      previous = now;
      const level = Number.isFinite(latest.current) ? Math.max(0, Math.min(1, latest.current)) : 0;
      if (level === 0 || Math.abs(level - heldLevel) >= .015) heldLevel = level;
      const target = heldLevel;
      const response = Math.abs(target - smoothed) < .06 ? 80 : target > smoothed ? 28 : 65;
      smoothed += (target - smoothed) * (1 - Math.exp(-elapsed / response));
      const phase = motion.matches ? 0 : (now - start) * .0032;
      Array.from(bars.current?.children ?? []).forEach((bar, index) => {
        const envelope = .58 + .42 * Math.sin(index / 11 * Math.PI);
        const amplitude = smoothed * 1.6 * envelope * (1 + .04 * Math.sin(phase + index * .82));
        (bar as HTMLElement).style.height = `${Math.max(4, Math.min(22, 4 + 18 * amplitude))}px`;
      });
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [active]);
  return <div ref={bars} className="pill-meter" aria-hidden="true">{Array.from({length:12}, (_, index) => <i key={index} />)}</div>;
}

export interface WorkflowState {
  surface: string; status: string; result: string; busy: boolean; recording: boolean;
  showRecordingStop: boolean; refinementFailed: boolean; canShowResult: boolean;
  canRetryTranscription: boolean; cancellationVisible: boolean; canUndoCancellation: boolean;
  feedbackVisible: boolean; feedbackOperationId: number; feedbackTitle: string; completionId: string; recordingShortcut: string;
  transitionPending: boolean; writingStyleCaption: string; writingStyleFinished: boolean;
  writingStyleApplied: boolean; mode: string; language: string;
  translationOptions: {code: string; label?: string; name?: string}[];
  canPasteLastTranscription: boolean; recordingReady: boolean; level: number; levels: number[]; uiLanguage: string;
  targetIcon: string;
  microphoneDevices: {id: string; label: string}[]; quickMicrophoneId: string; microphoneInventoryBusy: boolean;
  textActions: {id: string; name: string; enabled: boolean}[];
  updateAvailable: boolean; updateBusy: boolean; updateVersion: string;
  dictationWritingStyle: WritingStyle | ''; writingStyleRefinementAllowed: boolean;
}
type Method = 'startRecordingFromButton' | 'stopRecording' | 'cancelRecording' | 'chooseTranslation' | 'cancelTranslation' | 'openSettings' | 'openFiles' | 'showResult' | 'copyResult' | 'finish' | 'reset' | 'undoCancellation' | 'dismissFeedback' | 'retryTranscription' | 'pasteLastTranscription' | 'toggleWindow' | 'quit' | 'runTextAction' | 'selectQuickMicrophone' | 'refreshMicrophones' | 'installUpdate';
function languageName(code: string, locale: string) {
  const name = new Intl.DisplayNames([locale], {type:'language'}).of(code) || code;
  return name.charAt(0).toLocaleUpperCase(locale) + name.slice(1);
}
export function Pill() {
  const [state, setState] = useState<Partial<WorkflowState>>({surface: 'idle'});
  const [error, setError] = useState('');
  const moreOptions = useRef<HTMLButtonElement>(null);
  const [menu, setMenu] = useState(false);
  const [languageMenu, setLanguageMenu] = useState(false);
  const [submenu, setSubmenu] = useState<'microphone' | 'actions' | null>(null);
  const quickMenu = useRef<HTMLElement>(null);
  const sideMenu = useRef<HTMLElement>(null);
  const microphoneTrigger = useRef<HTMLButtonElement>(null);
  const actionsTrigger = useRef<HTMLButtonElement>(null);
  const submenuTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const focusSubmenu = useRef(false);
  const [submenuPosition, setSubmenuPosition] = useState({left: 8, top: 8});
  const clearSubmenuTimer = () => { clearTimeout(submenuTimer.current); submenuTimer.current = undefined; };
  const openSubmenu = (next: 'microphone' | 'actions' | null, keyboard = false) => {
    clearSubmenuTimer();
    if (keyboard && next === submenu) {
      const first = sideMenu.current?.querySelector<HTMLButtonElement>('button:not(:disabled)');
      focusSubmenu.current = !first; first?.focus({preventScroll:true}); return;
    }
    focusSubmenu.current = keyboard;
    setSubmenu(next);
  };
  const hoverSubmenu = (next: 'microphone' | 'actions' | null) => {
    clearSubmenuTimer();
    submenuTimer.current = setTimeout(() => { focusSubmenu.current = false; setSubmenu(next); }, 120);
  };
  useEffect(() => {
    clearSubmenuTimer();
    return clearSubmenuTimer;
  }, [menu, state.surface]);
  useLayoutEffect(() => {
    if (!menu || !submenu || !quickMenu.current || !sideMenu.current) return;
    const parent = quickMenu.current.getBoundingClientRect();
    const trigger = (submenu === 'microphone' ? microphoneTrigger : actionsTrigger).current?.getBoundingClientRect();
    const child = sideMenu.current.getBoundingClientRect();
    const right = parent.right + 6;
    const left = Math.max(8, Math.min(innerWidth - child.width - 8, right + child.width <= innerWidth - 8 ? right : parent.left - child.width - 6));
    const top = Math.max(8, Math.min(trigger?.top ?? parent.top, innerHeight - child.height - 8));
    setSubmenuPosition(previous => previous.left === left && previous.top === top ? previous : {left, top});
    if (focusSubmenu.current) {
      const first = sideMenu.current.querySelector<HTMLButtonElement>('button:not(:disabled)');
      if (first) { focusSubmenu.current = false; first.focus({preventScroll:true}); }
    }
  }, [menu, submenu, state.microphoneDevices, state.microphoneInventoryBusy, state.textActions]);
  const dock = useDockPresentation(() => { setMenu(false); setLanguageMenu(false); setSubmenu(null); });
  const [completion, setCompletion] = useState("");
  const seenCompletion = useRef("");
  const feedbackLabel = useRef<HTMLSpanElement>(null);
  const feedbackActions = useRef<HTMLDivElement>(null);
  const feedbackLayer = useRef<HTMLDivElement>(null);
  const doneContent = useRef<HTMLSpanElement>(null);
  const [doneWidth, setDoneWidth] = useState(92);
  const retainedFeedback = useRef<Partial<WorkflowState>>({});
  if (state.feedbackVisible) retainedFeedback.current = state;
  const [feedbackWidth, setFeedbackWidth] = useState(242);
  useLayoutEffect(() => {
    if (!state.feedbackVisible) return;
    const layout = feedbackLayer.current && getComputedStyle(feedbackLayer.current);
    const inset = layout ? parseFloat(layout.paddingLeft) + parseFloat(layout.paddingRight) + parseFloat(layout.columnGap) : 60;
    setFeedbackWidth(Math.min(620, Math.max(120, Math.ceil((feedbackLabel.current?.scrollWidth || 0) + (feedbackActions.current?.offsetWidth || 0) + inset + 2))));
  }, [state.feedbackVisible, state.feedbackTitle, state.canUndoCancellation, state.canRetryTranscription, state.canShowResult, state.uiLanguage, state.targetIcon]);
  useLayoutEffect(() => {
    if (completion && doneContent.current) setDoneWidth(Math.max(72, Math.ceil(doneContent.current.getBoundingClientRect().width) + 24));
  }, [completion, state.uiLanguage]);
  const run = (method: Method, ...args: unknown[]) => {
    setMenu(false); setLanguageMenu(false); setSubmenu(null); setError('');
    void electron()?.call('workflow', method, args).catch(error => setError(String(error)));
  };
  useEffect(() => {
    dock.workflowChanged();
  }, [state.surface]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (submenu) { clearSubmenuTimer(); setSubmenu(null); (submenu === 'microphone' ? microphoneTrigger : actionsTrigger).current?.focus(); return; }
      if (menu || languageMenu) { if (menu) moreOptions.current?.focus(); setMenu(false); setLanguageMenu(false); return; }
      if (state.surface === 'translation_picker') run('cancelTranslation');
      else if (['result', 'voice_result', 'voice_error'].includes(state.surface || '')) run('reset');
      else dock.collapse();
    };
    document.addEventListener('keydown', key);
    return () => document.removeEventListener('keydown', key);
  }, [state.surface, menu, languageMenu, submenu]);
  useEffect(() => {
    if (state.surface !== 'translation_picker') return;
    const focusLanguage = () => {
      const list = document.querySelector('.pill-languages');
      if (!list?.contains(document.activeElement)) list?.querySelector<HTMLButtonElement>('button')?.focus({preventScroll: true});
    };
    focusLanguage();
    window.addEventListener('focus', focusLanguage);
    return () => window.removeEventListener('focus', focusLanguage);
  }, [state.surface]);
  useEffect(() => {
    document.documentElement.classList.add('pill-surface');
    document.title = 'Clarify';
    const off = electron()?.subscribe(message => {
      if (message.event === 'workflow') { const next = message.state as unknown as WorkflowState; setUiLanguage(next.uiLanguage); setState(next); }
    });
    void electron()?.ready();
    return () => {
      off?.(); document.documentElement.classList.remove('pill-surface');
    };
  }, []);
  useLayoutEffect(() => {
    if (!state.completionId || state.busy || state.recording || state.transitionPending || state.feedbackVisible) { setCompletion(""); return; }
    if (seenCompletion.current === state.completionId) return;
    seenCompletion.current = state.completionId;
    setCompletion(state.completionId);
    const timer = setTimeout(() => setCompletion(""), 1200);
    return () => clearTimeout(timer);
  }, [state.completionId, state.busy, state.recording, state.transitionPending, state.feedbackVisible]);
  useEffect(() => {
    if (!state.feedbackVisible || state.canRetryTranscription) return;
    const timer = setTimeout(() => run('dismissFeedback', state.feedbackOperationId), state.cancellationVisible || state.refinementFailed ? 5000 : 3200);
    return () => clearTimeout(timer);
  }, [state.feedbackVisible, state.feedbackOperationId, state.canRetryTranscription, state.cancellationVisible, state.refinementFailed]);
  // Native hit testing must follow the painted edges throughout expansion.
  useLayoutEffect(() => {
    const elements = Array.from(document.querySelectorAll('[data-pill-interactive]'));
    const update = () => void electron()?.window('regions', elements.map(element => {
      const bounds = element.getBoundingClientRect();
      const padding = element.hasAttribute("data-dock-hover-target") ? 8 : 0;
      const x = Math.max(0, bounds.x - padding), y = Math.max(0, bounds.y - padding);
      return {x, y, width: Math.min(innerWidth, bounds.right + padding) - x, height: Math.min(innerHeight, bounds.bottom + padding) - y};
    }));
    const observer = new ResizeObserver(update);
    window.addEventListener('resize', update);
    elements.forEach(element => observer.observe(element)); update();
    let frame = 0;
    const until = performance.now() + 400;
    const animateRegions = () => { update(); if (performance.now() < until) frame = requestAnimationFrame(animateRegions); };
    frame = requestAnimationFrame(animateRegions);
    return () => { cancelAnimationFrame(frame); observer.disconnect(); window.removeEventListener('resize', update); };
  }, [state.surface, menu, languageMenu, submenu, submenuPosition, completion, error, dock.expanded, state.feedbackVisible]);
  const button = (label: string, icon: React.ReactNode, method: Method, disabled = false) => <button type="button" aria-label={t(label)} disabled={disabled} onClick={() => run(method)}>{icon}<span className="pill-tooltip">{method === 'startRecordingFromButton' ? <>{t('Ditar')}{state.recordingShortcut && <kbd>{state.recordingShortcut}</kbd>}</> : t(label)}</span></button>;
  const processing = state.busy || state.transitionPending || state.surface === 'processing' || state.surface === 'voice_processing';
  const result = ['result', 'voice_result', 'voice_error'].includes(state.surface || '');
  const translation = state.surface === 'translation_picker';
  const feedback = retainedFeedback.current;
  const done = !!completion && !processing && !state.recording && !state.feedbackVisible;
  const capture = !!(state.recording || processing || state.feedbackVisible || done);
  const starting = state.transitionPending || (state.recording && !state.recordingReady);
  const width = state.feedbackVisible ? feedbackWidth : done ? doneWidth : state.recording ? (state.showRecordingStop ? (starting ? 112 : 128) : starting ? (state.targetIcon ? 96 : 72) : state.targetIcon ? 104 : 72) : state.targetIcon ? 96 : 72;
  const collapsed = !dock.expanded && !capture && !result && !translation && !menu && !languageMenu && !error;
  return <main className="pill-stage" onPointerDownCapture={dock.press} onPointerUpCapture={dock.release} onPointerCancelCapture={dock.release}>
    <section data-pill-interactive data-dock-hover-target={!result && !translation ? "" : undefined} data-collapsed={collapsed} data-surface={state.surface} data-feedback={!!state.feedbackVisible} data-starting={!!starting} data-done={done} data-target={!!state.targetIcon} data-recording={!!state.recording} className={`workflow-pill ${result || translation ? 'pill-panel' : capture ? 'pill-capture' : 'pill-idle'}${collapsed ? ' pill-collapsed' : ''}`} aria-label={t(state.status || 'Clarify')}
      style={capture && !result && !translation ? {width} : undefined}
      tabIndex={!capture && !result && !translation ? 0 : undefined}
      onPointerEnter={dock.pointerEnter} onPointerLeave={dock.pointerLeave}
      onFocusCapture={dock.expand}
      onKeyDown={event => {
        if (!capture && !result && !translation && (event.key === 'Enter' || event.key === ' ') && event.target === event.currentTarget) { event.preventDefault(); dock.expand(); return; }
        if (!translation || !['ArrowDown', 'ArrowUp'].includes(event.key)) return;
        event.preventDefault();
        const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('.pill-languages button'));
        if (!buttons.length) return;
        const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
        const next = index < 0 ? (event.key === 'ArrowDown' ? 0 : buttons.length - 1) : (index + (event.key === 'ArrowDown' ? 1 : buttons.length - 1)) % buttons.length;
        buttons[next]?.focus();
      }}
    >
      <span className="dock-handle" aria-hidden="true" />
      <div className="pill-content" inert={collapsed} aria-hidden={collapsed}>
      {result ? <>
        <div className="pill-result" aria-label={t('Resultado')}>{state.result || t(state.status || '')}</div>
        <div className="pill-actions">{button('Copiar', <Copy />, 'copyResult')}{button('Concluir', <Check />, state.surface === 'result' ? 'finish' : 'reset')}{button('Fechar', <X />, 'reset')}</div>
      </> : translation ? <>
        <div className="pill-actions"><span>{t('Traduzir para')}</span>{button('Cancelar', <X />, 'cancelTranslation')}</div>
        <div className="pill-languages">{state.translationOptions?.map(option => <button key={option.code} onClick={() => run('chooseTranslation', option.code)}><LanguageMark code={option.code} /><span>{option.label || option.name || option.code}</span></button>)}</div>
      </> : capture ? <>
        {state.targetIcon && !done && (!state.showRecordingStop || state.feedbackVisible) && <img className="pill-target-icon" src={state.targetIcon} alt="" />}
        <span className="pill-sr-only" role="status">{t(done ? 'Concluído' : state.feedbackVisible ? state.feedbackTitle || '' : state.status || '')}</span>
        <div className="pill-live-layer" data-visible={!state.feedbackVisible} aria-hidden={!!state.feedbackVisible}>
          <div className="pill-motion-layer" data-visible={!!starting}><LoaderCircle className="pill-spinner" /></div>
          <div className="pill-motion-layer" data-visible={!!state.recording && !starting}>
            <CaptureWave level={state.level || 0} active={!!state.recording && !starting && !state.feedbackVisible} />
          </div>
          <div className="pill-motion-layer" data-visible={!!processing && !starting && !state.recording}><div className="pill-typing" aria-hidden="true"><i /><i /><i /></div></div>
          <div className="pill-motion-layer pill-done-layer" data-visible={done}><span className="pill-done-content" ref={doneContent}><Check className="pill-success" /><span>{t("Concluído")}</span></span></div>
          {state.showRecordingStop && <div className="pill-cancel">{button('Cancelar gravação', <X />, 'cancelRecording', !state.recordingReady || !!state.feedbackVisible)}</div>}
          {state.showRecordingStop && <div className="pill-stop">{button('Parar gravação', <Square />, 'stopRecording', !state.recordingReady || !!state.feedbackVisible)}</div>}
        </div>
        <div ref={feedbackLayer} className="pill-feedback-layer" data-visible={!!state.feedbackVisible} aria-hidden={!state.feedbackVisible}>
          <span ref={feedbackLabel} className="pill-feedback-label">{t(feedback.feedbackTitle || '')}</span>
          <div ref={feedbackActions} className="pill-feedback-actions">
            {feedback.cancellationVisible ? <button className="pill-undo" disabled={!state.feedbackVisible || !state.canUndoCancellation} onClick={() => run('undoCancellation')}>{t('Desfazer')}</button> : <>
              {feedback.canShowResult && button('Ver resultado', <Copy />, 'showResult', !state.feedbackVisible)}
              {feedback.canRetryTranscription && button('Tentar novamente', <RotateCcw />, 'retryTranscription', !state.feedbackVisible)}
              <button aria-label={t('Fechar')} disabled={!state.feedbackVisible} onClick={() => run('dismissFeedback', state.feedbackOperationId)}><X /></button>
            </>}
          </div>
        </div>
      </> : <>
          {button('Iniciar gravação', <Mic />, 'startRecordingFromButton')}
          <button className="pill-language" aria-label={t('Idioma de saída')} aria-expanded={languageMenu} onClick={() => {clearSubmenuTimer(); setSubmenu(null); setLanguageMenu(!languageMenu); setMenu(false);}}><LanguageMark code={state.language} /><span className="pill-tooltip">{t("Idioma de saída")}</span></button>
          <button ref={moreOptions} aria-label={t('Mais opções')} aria-expanded={menu} onClick={() => {
            setMenu(!menu); setLanguageMenu(false); setSubmenu(null);
            if (!menu) void electron()?.call('workflow', 'refreshMicrophones', []).catch(error => setError(String(error)));
          }}><Settings /><span className="pill-tooltip">{t("Mais opções")}</span>{state.updateAvailable && <i className="pill-update-dot" />}</button>
      </>}
      </div>
    </section>
    {languageMenu && <nav data-pill-interactive className="pill-menu pill-language-menu" onPointerEnter={dock.pointerEnter} onPointerLeave={dock.pointerLeave} aria-label={t('Idioma de saída')}>
      {['auto', 'en', 'pt', 'es', 'de', 'ru'].map(code => <button key={code} aria-pressed={state.language === code} onClick={() => {
        setLanguageMenu(false);
        void electron()?.call('settings', 'savePreference', ['setLanguage', [code]]).catch(error => setError(String(error)));
      }}><LanguageMark code={code} /><span>{code === 'auto' ? t('Idioma original') : languageName(code, state.uiLanguage || 'en')}</span>{state.language === code && <Check className="language-selected" />}</button>)}
    </nav>}
    {menu && <nav ref={quickMenu} data-pill-interactive className="pill-menu pill-quick-menu" onPointerEnter={dock.pointerEnter} onPointerLeave={dock.pointerLeave} aria-label={t('Mais opções')}>
      <button ref={microphoneTrigger} className="pill-submenu-trigger" aria-haspopup="menu" aria-expanded={submenu === 'microphone'}
        onPointerEnter={() => hoverSubmenu('microphone')} onClick={() => openSubmenu('microphone')}
        onKeyDown={event => { if (event.key === 'ArrowRight') { event.preventDefault(); openSubmenu('microphone', true); } }}><Mic />{t('Microfone')}<ChevronRight className="pill-submenu-chevron" aria-hidden /></button>
      <button ref={actionsTrigger} className="pill-submenu-trigger" aria-haspopup="menu" aria-expanded={submenu === 'actions'}
        onPointerEnter={() => hoverSubmenu('actions')} onClick={() => openSubmenu('actions')}
        onKeyDown={event => { if (event.key === 'ArrowRight') { event.preventDefault(); openSubmenu('actions', true); } }}><Sparkles aria-hidden />{t('Ações de texto')}<ChevronRight className="pill-submenu-chevron" aria-hidden /></button>
      <button onPointerEnter={() => hoverSubmenu(null)} onClick={() => run('openSettings')}><Settings />{t('Configurações')}</button>
      <button onPointerEnter={() => hoverSubmenu(null)} onClick={() => run('openFiles')}><FileAudio />{t('Transcrever arquivos')}</button>
      <button onPointerEnter={() => hoverSubmenu(null)} disabled={!state.canPasteLastTranscription} onClick={() => run('pasteLastTranscription')}><ClipboardPaste />{t('Colar última transcrição')}</button>
      {state.updateAvailable && <button onPointerEnter={() => hoverSubmenu(null)} disabled={state.updateBusy} onClick={() => run('installUpdate')}><RotateCcw />{t('Instalar atualização')} {state.updateVersion}</button>}
    </nav>}
    {menu && submenu && <nav ref={sideMenu} data-pill-interactive className="pill-menu pill-submenu" role="menu" style={submenuPosition}
      aria-label={t(submenu === 'microphone' ? 'Microfone' : 'Ações de texto')}
      onPointerEnter={() => { clearSubmenuTimer(); dock.pointerEnter(); }} onPointerLeave={dock.pointerLeave}
      onKeyDown={event => {
        if (event.key === 'ArrowLeft') { event.preventDefault(); event.stopPropagation(); openSubmenu(null); (submenu === 'microphone' ? microphoneTrigger : actionsTrigger).current?.focus(); }
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          event.preventDefault(); const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'));
          const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
          buttons[(index + (event.key === 'ArrowDown' ? 1 : buttons.length - 1)) % buttons.length]?.focus();
        }
      }}>
      {submenu === 'microphone' ? state.microphoneDevices?.length ? state.microphoneDevices.map(device => <button key={device.id} role="menuitemradio" aria-checked={state.quickMicrophoneId === device.id}
        disabled={state.microphoneInventoryBusy} onClick={() => run('selectQuickMicrophone', device.id)}><Check className="pill-submenu-check" data-selected={state.quickMicrophoneId === device.id} aria-hidden /><span>{device.label}</span></button>)
        : <button role="menuitem" disabled>{t(state.microphoneInventoryBusy ? 'Carregando…' : 'Sem microfones')}</button>
        : state.textActions?.length ? state.textActions.map(action => <button key={action.id} role="menuitem" disabled={!action.enabled || state.busy} onClick={() => run('runTextAction', action.id)}>{action.name}</button>)
        : <button role="menuitem" disabled>{t('Nenhuma ação salva.')}</button>}
    </nav>}
    {error && <div data-pill-interactive className="pill-error" onPointerEnter={dock.pointerEnter} onPointerLeave={dock.pointerLeave} role="alert">{error}<button onClick={() => setError('')} aria-label={t('Fechar')}><X /></button></div>}
  </main>;
}
