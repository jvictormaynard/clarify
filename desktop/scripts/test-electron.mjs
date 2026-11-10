import {chromium, expect} from '@playwright/test';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {mkdir, mkdtemp, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createTestEnvironment} from './test-environment.mjs';
const root = fileURLToPath(new URL('..', import.meta.url));
if (!process.env.CLARIFY_TEST_PYTHON || !process.env.CLARIFY_TEST_FIXTURE) throw new Error('Set CLARIFY_TEST_PYTHON and CLARIFY_TEST_FIXTURE.');
const environment = await createTestEnvironment('clarify-electron-smoke-profile-');
const evidenceRoot = process.env.CLARIFY_TEST_ARTIFACTS_DIR || tmpdir();
await mkdir(evidenceRoot, {recursive:true});
const evidence = await mkdtemp(join(evidenceRoot, 'clarify-electron-evidence-'));
let app, fixture, hostProcess;
const messages = [], errors = [];
const nativePending = new Map(); let nativeId = 0;
try {
  const env = {...environment.env, CLARIFY_TEST_UI_LANGUAGE: 'en'};
  delete env.ELECTRON_RUN_AS_NODE;
  fixture = spawn(process.env.CLARIFY_TEST_PYTHON, ['-u', process.env.CLARIFY_TEST_FIXTURE], {env, windowsHide: true});
  fixture.stderr.on('data', data => errors.push(String(data)));
  // Playwright's Electron launcher ignores stdin. Spawn the real package with
  // pipes and attach CDP to preserve the production Python transport contract.
  hostProcess = spawn(join(root, 'electron-dist/Clarify Desktop-win32-x64/Clarify Desktop.exe'),
    ['--remote-debugging-port=0', '--user-data-dir=' + join(environment.profile, 'chromium')], {env, windowsHide:true, stdio:'pipe'});
  const endpoint = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('No packaged Chromium endpoint')),30000);
    hostProcess.once('error', reject);
    hostProcess.once('exit', code => { clearTimeout(timer); reject(new Error('Package exited: '+code)); });
    createInterface({input:hostProcess.stderr}).on('line', line => {
      errors.push(line);
      const match = /DevTools listening on (ws:\/\/.*)/.exec(line);
      if (match) { clearTimeout(timer); resolve(match[1]); }
    });
  });
  const send = value => hostProcess.stdin.write(JSON.stringify(value) + '\n');
  createInterface({input: fixture.stdout}).on('line', line => {
    const reply=JSON.parse(line), pending=nativePending.get(reply.id);
    if (pending) { nativePending.delete(reply.id); pending(reply.result); }
    else hostProcess.stdin.write(line + '\n');
  });
  const nativeInput = value => new Promise((resolve, reject) => {
    const id=--nativeId, timer=setTimeout(()=>{nativePending.delete(id);reject(new Error('Native input timed out'));},10000);
    nativePending.set(id,result=>{clearTimeout(timer);resolve(result);});
    fixture.stdin.write(JSON.stringify({id,method:'nativePillInput',args:[{pid:hostProcess.pid,...value}]})+'\n');
  });
  createInterface({input: hostProcess.stdout}).on('line', line => {
    let value;
    if (!line.trim()) return;
    try { value = JSON.parse(line); } catch { errors.push('Non-JSON stdout: ' + line); return; }
    messages.push(value);
    if (value.channel === 'settings') fixture.stdin.write(JSON.stringify(value) + '\n');
    if (value.channel === 'workflow') send({id: value.id, result: null});
  });
  app = await chromium.connectOverCDP(await endpoint);
  await expect.poll(() => app.contexts()[0].pages().length).toBe(2);
  const settings = app.contexts()[0].pages().find(page => !page.url().includes('surface=pill'));
  const pill = app.contexts()[0].pages().find(page => page.url().includes('surface=pill'));
  const rendererErrors = []; for (const page of [settings, pill]) page.on('pageerror', error => rendererErrors.push(String(error)));
  await expect(settings.getByRole('combobox', {name:'Microphone', exact:true})).toBeVisible({timeout:30000});
  await expect.poll(() => messages.some(message => message.event === 'ready')).toBe(true);
  send({window:'settings-show'});
  expect(await settings.locator('.titlebar').evaluate(node => getComputedStyle(node).getPropertyValue('-webkit-app-region'))).toBe('drag');
  await settings.getByRole('button', {name:'Dictionary', exact:true}).click();
  await settings.getByRole('textbox', {name:'New term', exact:true}).fill('Electron draft');
  await settings.getByRole('button', {name:'Add term', exact:true}).click();
  await settings.getByRole('button', {name:'Close window', exact:true}).click();
  await expect(settings.getByRole('dialog', {name:'Unsaved changes', exact:true})).toBeVisible();
  await settings.getByRole('button', {name:'Keep editing', exact:true}).click();
  await expect(settings.locator('[role=dialog]')).toHaveCount(0);
  await settings.screenshot({path:join(evidence, 'settings-draft.png')});
  await settings.getByRole('button', {name:'Close window', exact:true}).click();
  await settings.getByRole('button', {name:'Discard all', exact:true}).click();
  await expect.poll(() => messages.filter(message => message.event === 'settings-hidden').length).toBe(1);
  send({window:'settings-show'});
  await settings.getByRole('textbox', {name:'New term', exact:true}).fill('Second draft');
  await settings.getByRole('button', {name:'Add term', exact:true}).click();
  await settings.getByRole('button', {name:'Close window', exact:true}).click();
  await expect(settings.getByRole('dialog', {name:'Unsaved changes', exact:true})).toBeVisible();
  await settings.getByRole('button', {name:'Discard all', exact:true}).click();
  const initial = {surface:'idle', status:'', result:'', busy:false, recording:false, uiLanguage:'en', language:'auto', levels:[], translationOptions:[], dictationWritingStyle:'natural', applicationStyleRefinementAllowed:true};
  const state = async (name, patch) => {
    send({event:'workflow', state:{...initial,...patch}}); send({window:'pill-show'});
    await expect(pill.locator('.workflow-pill')).toHaveAttribute('data-surface', patch.surface || 'idle');
    await pill.locator('.workflow-pill').evaluate(async node => {
      await Promise.all(node.getAnimations({subtree:true}).filter(animation => animation instanceof CSSTransition && ['width', 'opacity', 'translate', 'border-color'].includes(animation.transitionProperty)).map(animation => animation.finished.catch(() => {})));
    });
    if (patch.feedbackTitle) await expect(pill.getByRole('status')).toHaveText(patch.feedbackTitle);
    await expect.poll(() => pill.evaluate(() => document.documentElement.classList.contains('pill-surface'))).toBe(true);
    await pill.screenshot({path:join(evidence, name + '.png'), omitBackground:true});
  };
  await state('idle', {});
  const idleBounds = await pill.locator('.workflow-pill').boundingBox();
  expect(idleBounds.width).toBeLessThan(140);
  await expect(pill.getByText('Ready to capture your voice', {exact:true})).toHaveCount(0);
  if (process.platform === 'win32') {
    const nativeDrags=[];
    for (const [dx,dy] of [[0,-40],[50,0],[0,40],[-50,0]]) {
      const before=await nativeInput({action:'bounds'}), rect=await pill.locator('.workflow-pill').boundingBox();
      const viewport=await pill.evaluate(()=>({width:innerWidth,height:innerHeight}));
      const x=before.x+(rect.x+rect.width/2)*before.width/viewport.width, y=before.y+(rect.y+4)*before.height/viewport.height;
      await nativeInput({action:'move',x,y}); await new Promise(resolve=>setTimeout(resolve,100));
      await expect.poll(async()=>(await nativeInput({action:'bounds'})).receives).toBe(true);
      await nativeInput({action:'down'});
      try {
        for(let step=1;step<=4;step++){await nativeInput({action:'move',x:x+dx*step/4,y:y+dy*step/4});await new Promise(resolve=>setTimeout(resolve,70));}
      } finally { await nativeInput({action:'up'}); }
      await expect.poll(async()=>(await nativeInput({action:'bounds'})).capture).toBe(false);
      const after=await nativeInput({action:'bounds'});
      nativeDrags.push({before,after,dx,dy});await writeFile(join(evidence,'native-drags.json'),JSON.stringify(nativeDrags,null,2));
      expect(after.width).toBe(before.width); expect(after.height).toBe(before.height);
      expect(Math.abs(after.x-before.x-dx)).toBeLessThanOrEqual(14);
      expect(Math.abs(after.y-before.y-dy)).toBeLessThanOrEqual(14);
    }
    const bounds=await nativeInput({action:'bounds'}), rect=await pill.locator('.pill-language').boundingBox();
    const viewport=await pill.evaluate(()=>({width:innerWidth,height:innerHeight}));
    await nativeInput({action:'move',x:bounds.x+(rect.x+rect.width/2)*bounds.width/viewport.width,y:bounds.y+(rect.y+rect.height/2)*bounds.height/viewport.height});
    await new Promise(resolve=>setTimeout(resolve,100)); await nativeInput({action:'down'}); await nativeInput({action:'up'});
    await expect(pill.locator('.pill-language-menu')).toBeVisible();
    await pill.locator('.pill-language').click();
  }
  await pill.getByRole('button', {name:'Start recording',exact:true}).click();
  await expect.poll(() => messages.some(message => message.method === 'startRecordingFromButton')).toBe(true);
  await state('starting', {surface:'recording',recording:true,recordingReady:false,showRecordingStop:true,transitionPending:true});
  const spinner = await pill.locator('.pill-motion-layer:has(.pill-spinner)').boundingBox();
  const stop = await pill.getByRole('button', {name:'Stop recording',exact:true}).boundingBox();
  expect(spinner.x + spinner.width).toBeLessThan(stop.x);
  await expect(pill.getByRole('button', {name:'Stop recording',exact:true})).toBeDisabled();
  await state('recording', {surface:'recording',recording:true, recordingReady:true,showRecordingStop:true,level:.35, status:'Listening to your microphone'});
  const recordingBounds = await pill.locator('.workflow-pill').boundingBox();
  expect(recordingBounds.height).toBe(idleBounds.height);
  expect(recordingBounds.y).toBe(idleBounds.y);
  await expect(pill.locator('.pill-meter i')).toHaveCount(12);
  await expect(pill.locator('.pill-caption')).toHaveCount(0);
  const heights = () => pill.locator('.pill-meter i').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().height));
  const waveBefore = await heights();
  await expect.poll(heights).not.toEqual(waveBefore);
  const startWidth = await pill.locator('.workflow-pill').evaluate(node => node.getBoundingClientRect().width);
  send({event:'workflow',state:{...initial,feedbackVisible:true,feedbackTitle:'Recording cancelled',canUndoCancellation:true,cancellationVisible:true,feedbackOperationId:1}});
  await expect(pill.locator('.workflow-pill')).toHaveAttribute('data-feedback','true');
  const runningTransition = await pill.locator('.workflow-pill').evaluate(node => node.getAnimations().some(animation => animation.playState === 'running'));
  expect(runningTransition).toBe(true);
  await pill.screenshot({path:join(evidence,'recording-to-cancelled.png'),omitBackground:true});
  await expect.poll(() => pill.locator('.workflow-pill').evaluate(node => node.getBoundingClientRect().width)).toBeGreaterThan(startWidth);
  await state('undo', {feedbackVisible:true,feedbackTitle:'Recording cancelled',canUndoCancellation:true,cancellationVisible:true,feedbackOperationId:1});
  const cancelledBounds = await pill.locator('.workflow-pill').boundingBox();
  expect(cancelledBounds.height).toBe(idleBounds.height);
  expect(cancelledBounds.y).toBe(idleBounds.y);
  await pill.getByRole('button', {name:'Undo',exact:true}).click();
  await state('processing', {surface:'processing',busy:true,status:'Processing'});
  await expect(pill.locator('.pill-progress')).toBeVisible();
  await expect(pill.getByText('Processing',{exact:true})).toHaveClass('pill-sr-only');
  await state('retry', {surface:'error',feedbackVisible:true,feedbackTitle:'Transcription failed',canRetryTranscription:true,feedbackOperationId:2});
  await pill.getByRole('button', {name:'Try again',exact:true}).click();
  await state('preserved-result', {surface:'error',feedbackVisible:true,feedbackTitle:'Refinement failed',canShowResult:true,feedbackOperationId:3});
  await pill.getByRole('button', {name:'Show result',exact:true}).click();
  await expect.poll(() => messages.some(message => message.method === 'showResult')).toBe(true);
  await state('result', {surface:'result',result:'Independent Electron renderer result.'});
  await expect(pill.getByText('Independent Electron renderer result.')).toBeVisible();
  await state('translation', {surface:'translation_picker',translationOptions:[{code:'en',label:'English'},{code:'pt',label:'Portuguese'},{code:'es',label:'Spanish'},{code:'de',label:'German'},{code:'ru',label:'Russian'}]});
  await expect(pill.locator('.pill-languages .language-mark[data-language]')).toHaveCount(5);
  const translationBounds = await pill.locator('.workflow-pill').boundingBox();
  expect(translationBounds.width).toBeLessThanOrEqual(226);
  expect(await pill.locator('.pill-languages').evaluate(node => node.scrollHeight > node.clientHeight)).toBe(false);
  await expect(pill.getByRole('button', {name:'English',exact:true})).toBeFocused();
  const translationKey = key => process.platform === 'win32' ? nativeInput({action:'key',key}) : pill.keyboard.press(key);
  if (process.platform === 'win32') {
    await expect.poll(async () => (await nativeInput({action:'bounds'}))?.foreground).toBe(true);
  }
  await translationKey('ArrowUp');
  await expect(pill.getByRole('button', {name:'Russian',exact:true})).toBeFocused();
  await translationKey('ArrowDown');
  await expect(pill.getByRole('button', {name:'English',exact:true})).toBeFocused();
  await translationKey('ArrowDown');
  await expect(pill.getByRole('button', {name:'Portuguese',exact:true})).toBeFocused();
  await pill.screenshot({path:join(evidence,'translation-compact.png'), omitBackground:true});
  await translationKey('Enter');
  await expect.poll(() => messages.some(message => message.method === 'chooseTranslation' && message.args[0] === 'pt')).toBe(true);
  await state('success', {surface:'success'});
  await state('idle-menu', {});
  await pill.getByRole('button', {name:'More options',exact:true}).click();
  await pill.getByRole('button', {name:'Tone',exact:true}).click();
  await expect(pill.getByRole('button', {name:'Keep my tone',exact:true})).toHaveAttribute('aria-pressed','true');
  await pill.getByRole('button', {name:'Formal',exact:true}).click();
  await expect.poll(() => messages.some(message => message.channel === 'settings' && message.method === 'savePreference' && message.args[0] === 'setDictationWritingStyle' && message.args[1][0] === 'formal')).toBe(true);
  await state('tone-selected', {dictationWritingStyle:'formal'});
  await pill.getByRole('button', {name:'More options',exact:true}).click();
  await pill.getByRole('button', {name:'Tone',exact:true}).click();
  await expect(pill.getByRole('button', {name:'Formal',exact:true})).toHaveAttribute('aria-pressed','true');
  await expect(pill.getByRole('alert')).toHaveCount(0);
  await pill.getByRole('button', {name:'Tone',exact:true}).click();
  await pill.screenshot({path:join(evidence,'idle-menu.png'), omitBackground:true});
  await pill.getByRole('button', {name:'Transcribe files',exact:true}).click();
  await expect.poll(() => messages.some(message => message.method === 'openFiles')).toBe(true);
  await pill.getByRole('button', {name:'Language',exact:true}).click();
  await expect(pill.locator('.pill-language-menu .language-mark[data-language]')).toHaveCount(5);
  await expect(pill.locator('.pill-language-menu .language-mark-original')).toHaveCount(1);
  const clipped = await pill.locator('.pill-language-menu').evaluate(node => node.scrollHeight > node.clientHeight);
  expect(clipped).toBe(false);
  await pill.screenshot({path:join(evidence,'language-menu.png'), omitBackground:true});
  await pill.getByRole('button', {name:'Portuguese',exact:true}).click();
  await expect.poll(() => messages.some(message => message.channel === 'settings' && message.method === 'savePreference' && message.args[0] === 'setLanguage')).toBe(true);
  const dpiSession = await app.contexts()[0].newCDPSession(pill);
  const viewport = await pill.evaluate(() => ({width: innerWidth, height: innerHeight}));
  for (const deviceScaleFactor of [1, 1.25, 1.5, 2]) {
    await dpiSession.send('Emulation.setDeviceMetricsOverride', {...viewport, deviceScaleFactor, mobile:false});
    const bounds = [];
    for (const patch of [{surface:'idle'}, {surface:'recording',recording:true,recordingReady:true}, {surface:'idle',feedbackVisible:true,feedbackTitle:'Recording cancelled',cancellationVisible:true,canUndoCancellation:true}]) {
      send({event:'workflow',state:{...initial,...patch}});
      await expect(pill.locator('.workflow-pill')).toHaveAttribute('data-surface', patch.surface);
      await expect(pill.locator('.workflow-pill')).toHaveAttribute('data-feedback', String(!!patch.feedbackVisible));
      bounds.push(await pill.locator('.workflow-pill').boundingBox());
    }
    expect(bounds.map(rect => rect.height)).toEqual([40,40,40]);
    expect(bounds[1].y).toBe(bounds[0].y); expect(bounds[2].y).toBe(bounds[0].y);
  }
  await dpiSession.send('Emulation.clearDeviceMetricsOverride'); await dpiSession.detach();
  send({event:'workflow',state:initial});
  await expect(pill.locator('.pill-idle')).toBeVisible();
  await pill.getByRole('button', {name:'More options',exact:true}).click();
  await pill.getByRole('button', {name:'Quit',exact:true}).click();
  await expect.poll(() => messages.some(message => message.event === 'quit')).toBe(true);
  for (const page of [settings,pill]) expect(await page.evaluate(() => typeof window.require)).toBe('undefined');
  const native = {transport:'real stdin/stdout pipes', renderer:'packaged Chromium over CDP'};
  expect(rendererErrors).toEqual([]);
  const closed = new Promise(resolve => hostProcess.once('exit',resolve)); hostProcess.stdin.end(); await closed;
  await writeFile(join(evidence,'result.json'), JSON.stringify({native,messages,rendererErrors,errors},null,2));
  console.log('PASS: packaged Electron Settings draft/reopen, pill commands and states, isolated renderer, EOF shutdown. Evidence: ' + evidence);
} finally {
  await writeFile(join(evidence,'diagnostics.json'), JSON.stringify({messages,errors},null,2));
  console.log('Electron evidence: ' + evidence);
  hostProcess?.kill(); fixture?.kill();
  await app?.close().catch(() => {});
  // Keep captures and diagnostics; remove only the isolated runtime profile.
  await environment.dispose();
}
