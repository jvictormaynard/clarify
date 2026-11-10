import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Check, Copy, FileAudio, LoaderCircle, Mic, RotateCcw, Settings, Square, X, ClipboardPaste, Power } from 'lucide-react';
import { LanguageMark } from './components/language-mark';
import { electron } from './platform';
import { setUiLanguage } from './i18n';
import { pillText as t } from './pill-labels';
import './styles/pill.css';
import type { WritingStyle } from './settings/bridge';
import { writingStyleOptions } from './settings/writing-style-options';

/** Same twelve-bar envelope and motion as StatusPill.qml; audio owns amplitude. */
function CaptureWave({level, active}: {level: number; active: boolean}) {
  const bars = useRef<HTMLDivElement>(null);
  const latest = useRef(level);
  latest.current = level;
  useEffect(() => {
    if (!active) return;
    const motion = matchMedia('(prefers-reduced-motion: reduce)');
    let frame = 0;
    const start = performance.now();
    const draw = (now: number) => {
      const phase = motion.matches ? 0 : (now - start) * .0053125;
      Array.from(bars.current?.children ?? []).forEach((bar, index) => {
        const envelope = .58 + .42 * Math.sin(index / 11 * Math.PI);
        const amplitude = Math.max(.22, Math.min(.98, (latest.current * 1.45 + .24 + .12 * Math.sin(phase + index * .82)) * envelope));
        (bar as HTMLElement).style.height = `${Math.max(6.4, 34 * amplitude)}px`;
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
  feedbackVisible: boolean; feedbackOperationId: number; feedbackTitle: string;
  transitionPending: boolean; writingStyleCaption: string; writingStyleFinished: boolean;
  writingStyleApplied: boolean; mode: string; language: string;
  translationOptions: {code: string; label?: string; name?: string}[];
  canPasteLastTranscription: boolean; recordingReady: boolean; level: number; levels: number[]; uiLanguage: string;
  targetIcon: string;
  microphoneDevices: {id: string; label: string}[]; quickMicrophoneId: string; microphoneInventoryBusy: boolean;
  textActions: {id: string; name: string; enabled: boolean}[];
  updateAvailable: boolean; updateBusy: boolean; updateVersion: string;
  dictationWritingStyle: WritingStyle | ''; applicationStyleRefinementAllowed: boolean;
}
type Method = 'startRecordingFromButton' | 'stopRecording' | 'cancelRecording' | 'chooseTranslation' | 'cancelTranslation' | 'openSettings' | 'openFiles' | 'showResult' | 'copyResult' | 'finish' | 'reset' | 'undoCancellation' | 'dismissFeedback' | 'retryTranscription' | 'pasteLastTranscription' | 'toggleWindow' | 'quit' | 'runTextAction' | 'selectQuickMicrophone' | 'refreshMicrophones' | 'installUpdate';
export function Pill() {
  const [state, setState] = useState<Partial<WorkflowState>>({surface: 'idle'});
  const [error, setError] = useState('');
  const moreOptions = useRef<HTMLButtonElement>(null);
  const [menu, setMenu] = useState(false);
  const [languageMenu, setLanguageMenu] = useState(false);
  const [submenu, setSubmenu] = useState<'microphone' | 'actions' | 'tone' | null>(null);
  const [success, setSuccess] = useState(true);
  const [styleFeedback, setStyleFeedback] = useState(false);
  const dragging = useRef(false);
  const feedbackLabel = useRef<HTMLSpanElement>(null);
  const feedbackActions = useRef<HTMLDivElement>(null);
  const retainedFeedback = useRef<Partial<WorkflowState>>({});
  if (state.feedbackVisible) retainedFeedback.current = state;
  const [feedbackWidth, setFeedbackWidth] = useState(242);
  useLayoutEffect(() => {
    if (!state.feedbackVisible) return;
    setFeedbackWidth(Math.min(620, Math.max(230, (feedbackLabel.current?.scrollWidth || 0) + (feedbackActions.current?.offsetWidth || 0) + 66)) + 12);
  }, [state.feedbackVisible, state.feedbackTitle, state.canUndoCancellation, state.canRetryTranscription, state.canShowResult, state.uiLanguage]);
  const run = (method: Method, ...args: unknown[]) => {
    setMenu(false); setLanguageMenu(false); setSubmenu(null); setError('');
    void electron()?.call('workflow', method, args).catch(error => setError(String(error)));
  };
  useEffect(() => {
    setMenu(false); setLanguageMenu(false);
  }, [state.surface]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (menu || languageMenu) { if (menu) moreOptions.current?.focus(); setMenu(false); setLanguageMenu(false); return; }
      if (state.surface === 'translation_picker') run('cancelTranslation');
      else if (['result', 'voice_result', 'voice_error'].includes(state.surface || '')) run('reset');
    };
    document.addEventListener('keydown', key);
    return () => document.removeEventListener('keydown', key);
  }, [state.surface, menu, languageMenu]);
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
      if (dragging.current) { dragging.current=false; void electron()?.window('dragEnd').catch(()=>{}); }
      off?.(); document.documentElement.classList.remove('pill-surface');
    };
  }, []);
  useEffect(() => {
    setSuccess(true);
    if (state.surface !== 'success') return;
    const timer = setTimeout(() => setSuccess(false), 850);
    return () => clearTimeout(timer);
  }, [state.surface]);
  useEffect(() => {
    setStyleFeedback(!!state.writingStyleFinished);
    const timer = setTimeout(() => setStyleFeedback(false), 2200);
    return () => clearTimeout(timer);
  }, [state.writingStyleFinished, state.feedbackOperationId]);
  useEffect(() => {
    if (!state.feedbackVisible || state.canRetryTranscription) return;
    const timer = setTimeout(() => run('dismissFeedback', state.feedbackOperationId), state.cancellationVisible || state.refinementFailed ? 5000 : 3200);
    return () => clearTimeout(timer);
  }, [state.feedbackVisible, state.feedbackOperationId, state.canRetryTranscription, state.cancellationVisible, state.refinementFailed]);
  // Publish painted bounds only when layout changes. The main process checks
  // the native cursor because Windows can stop forwarding ignored mouse moves.
  useLayoutEffect(() => {
    const elements = Array.from(document.querySelectorAll('[data-pill-interactive]'));
    if (!elements.length && dragging.current) { dragging.current=false; void electron()?.window('dragEnd'); }
    const update = () => void electron()?.window('regions', elements.map(element => {
      const {x, y, width, height} = element.getBoundingClientRect();
      return {x, y, width, height};
    }));
    const observer = new ResizeObserver(update);
    window.addEventListener('resize', update);
    elements.forEach(element => observer.observe(element)); update();
    return () => { observer.disconnect(); window.removeEventListener('resize', update); };
  }, [state.surface, menu, languageMenu, submenu, success, error]);
  const button = (label: string, icon: React.ReactNode, method: Method, disabled = false) => <button type="button" title={t(label)} aria-label={t(label)} disabled={disabled} onClick={() => run(method)}>{icon}</button>;
  const processing = state.busy || state.transitionPending || state.surface === 'processing' || state.surface === 'voice_processing';
  const result = ['result', 'voice_result', 'voice_error'].includes(state.surface || '');
  const translation = state.surface === 'translation_picker';
  const feedback = retainedFeedback.current;
  const capture = !!(state.recording || processing || state.feedbackVisible || state.surface === 'success' || styleFeedback);
  const starting = state.transitionPending || (state.recording && !state.recordingReady);
  const width = state.feedbackVisible ? feedbackWidth : (starting ? 88 : 168) + (state.showRecordingStop ? 34 : 0);
  if (state.surface === 'success' && !success && !state.feedbackVisible && !styleFeedback) return null;
  return <main className="pill-stage">
    <section data-pill-interactive data-surface={state.surface} data-feedback={!!state.feedbackVisible} data-starting={!!starting} className={`workflow-pill ${result || translation ? 'pill-panel' : capture ? 'pill-capture' : 'pill-idle'}`} aria-label={t(state.status || 'Clarify')}
      style={capture && !result && !translation ? {width: width * .8} : undefined}
      onKeyDown={event => {
        if (!translation || !['ArrowDown', 'ArrowUp'].includes(event.key)) return;
        event.preventDefault();
        const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('.pill-languages button'));
        if (!buttons.length) return;
        const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
        const next = index < 0 ? (event.key === 'ArrowDown' ? 0 : buttons.length - 1) : (index + (event.key === 'ArrowDown' ? 1 : buttons.length - 1)) % buttons.length;
        buttons[next]?.focus();
      }}
      onPointerDown={event => {
        if (result || translation || event.button !== 0 || (event.target as HTMLElement).closest('button')) return;
        dragging.current=true; event.currentTarget.setPointerCapture(event.pointerId);
        void electron()?.window('dragStart');
      }}
      onPointerMove={() => { if(dragging.current) void electron()?.window('dragMove'); }}
      onPointerUp={() => { if(dragging.current) void electron()?.window('dragEnd'); dragging.current=false; }}
      onLostPointerCapture={() => { if(dragging.current) void electron()?.window('dragEnd'); dragging.current=false; }}
      onPointerCancel={() => { if(dragging.current) void electron()?.window('dragEnd'); dragging.current=false; }}>
      <div className="pill-content">
      {result ? <>
        <div className="pill-result" aria-label={t('Resultado')}>{state.result || t(state.status || '')}</div>
        <div className="pill-actions">{button('Copiar', <Copy />, 'copyResult')}{button('Concluir', <Check />, state.surface === 'result' ? 'finish' : 'reset')}{button('Fechar', <X />, 'reset')}</div>
      </> : translation ? <>
        <div className="pill-actions"><span>{t('Traduzir para')}</span>{button('Cancelar', <X />, 'cancelTranslation')}</div>
        <div className="pill-languages">{state.translationOptions?.map(option => <button key={option.code} onClick={() => run('chooseTranslation', option.code)}><LanguageMark code={option.code} /><span>{option.label || option.name || option.code}</span></button>)}</div>
      </> : capture ? <>
        {state.targetIcon && <img className="pill-target-icon" src={state.targetIcon} alt="" />}
        <span className="pill-sr-only" role="status">{t(state.feedbackVisible ? state.feedbackTitle || '' : state.status || '')}</span>
        <div className="pill-live-layer" data-visible={!state.feedbackVisible} aria-hidden={!!state.feedbackVisible}>
          <div className="pill-motion-layer" data-visible={!!starting}><LoaderCircle className="pill-spinner" /></div>
          <div className="pill-motion-layer" data-visible={!!state.recording && !starting}>
            <CaptureWave level={state.level || 0} active={!!state.recording && !starting && !state.feedbackVisible} />
          </div>
          <div className="pill-motion-layer" data-visible={!!processing && !starting && !state.recording}><div className="pill-progress"><i /></div></div>
          <div className="pill-motion-layer" data-visible={state.surface === 'success' || (styleFeedback && !!state.writingStyleApplied)}><Check className="pill-success" /></div>
          {state.showRecordingStop && <div className="pill-stop">{button('Parar gravação', <Square />, 'stopRecording', !state.recordingReady || !!state.feedbackVisible)}</div>}
        </div>
        <div className="pill-feedback-layer" data-visible={!!state.feedbackVisible} aria-hidden={!state.feedbackVisible}>
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
          <button className="pill-language" title={t('Idioma')} aria-label={t('Idioma')} aria-expanded={languageMenu} onClick={() => {setLanguageMenu(!languageMenu); setMenu(false);}}><LanguageMark code={state.language} /></button>
          <button ref={moreOptions} title={t('Mais opções')} aria-label={t('Mais opções')} aria-expanded={menu} onClick={() => {
            setMenu(!menu); setLanguageMenu(false); setSubmenu(null);
            if (!menu) void electron()?.call('workflow', 'refreshMicrophones', []).catch(error => setError(String(error)));
          }}><Settings />{state.updateAvailable && <i className="pill-update-dot" />}</button>
          {button('Ocultar', <X />, 'toggleWindow')}
      </>}
      </div>
    </section>
    {languageMenu && <nav data-pill-interactive className="pill-menu pill-language-menu" aria-label={t('Idioma')}>
      {['auto', 'en', 'pt', 'es', 'de', 'ru'].map(code => <button key={code} aria-pressed={state.language === code} onClick={() => {
        setLanguageMenu(false);
        void electron()?.call('settings', 'savePreference', ['setLanguage', [code]]).catch(error => setError(String(error)));
      }}><LanguageMark code={code} /><span>{code === 'auto' ? t('Original language') : new Intl.DisplayNames([state.uiLanguage || 'en'], {type:'language'}).of(code)}</span>{state.language === code && <Check className="language-selected" />}</button>)}
    </nav>}
    {menu && <nav data-pill-interactive className="pill-menu" aria-label={t('Mais opções')}>
      <button aria-expanded={submenu === 'microphone'} onClick={() => setSubmenu(submenu === 'microphone' ? null : 'microphone')}><Mic />{t('Microfone')}</button>
      {submenu === 'microphone' && state.microphoneDevices?.map(device => <button key={device.id} disabled={state.microphoneInventoryBusy} aria-pressed={state.quickMicrophoneId === device.id} onClick={() => run('selectQuickMicrophone', device.id)}>{device.label}</button>)}
      {state.applicationStyleRefinementAllowed === true && <>
        <button aria-expanded={submenu === 'tone'} onClick={() => setSubmenu(submenu === 'tone' ? null : 'tone')}>{t('Tom')}</button>
        {submenu === 'tone' && writingStyleOptions(state.dictationWritingStyle ?? '').map(option => <button key={option.id}
          aria-pressed={(state.dictationWritingStyle ?? '') === option.id} disabled={state.busy}
          onClick={() => {
            setMenu(false); moreOptions.current?.focus();
            void electron()?.call('settings', 'savePreference', ['setDictationWritingStyle', [option.id]]).catch(error => setError(String(error)));
          }}>{option.label}</button>)}
      </>}
      <button aria-expanded={submenu === 'actions'} onClick={() => setSubmenu(submenu === 'actions' ? null : 'actions')}>{t('Ações de texto')}</button>
      {submenu === 'actions' && state.textActions?.map(action => <button key={action.id} disabled={!action.enabled || state.busy} onClick={() => run('runTextAction', action.id)}>{action.name}</button>)}
      <button onClick={() => run('openSettings')}><Settings />{t('Configurações')}</button>
      <button onClick={() => run('openFiles')}><FileAudio />{t('Transcrever arquivos')}</button>
      <button disabled={!state.canPasteLastTranscription} onClick={() => run('pasteLastTranscription')}><ClipboardPaste />{t('Colar última transcrição')}</button>
      {state.updateAvailable && <button disabled={state.updateBusy} onClick={() => run('installUpdate')}><RotateCcw />{t('Instalar atualização')} {state.updateVersion}</button>}
      <button onClick={() => run('quit')}><Power />{t('Sair')}</button>
    </nav>}
    {error && <div data-pill-interactive className="pill-error" role="alert">{error}<button onClick={() => setError('')} aria-label={t('Fechar')}><X /></button></div>}
  </main>;
}
