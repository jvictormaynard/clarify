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
let app, fixture, hostProcess, nativePassiveCheck, nativeInput;
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
  nativeInput = value => new Promise((resolve, reject) => {
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
  await expect(settings.getByRole('heading', {level:1, name:'Welcome back', exact:true})).toBeVisible({timeout:30000});
  await expect(settings.locator('main .page-content')).toBeVisible();
  await expect.poll(() => messages.some(message => message.event === 'ready')).toBe(true);
  send({window:'settings-show'});
  expect(await settings.locator('.titlebar').evaluate(node => getComputedStyle(node).getPropertyValue('-webkit-app-region'))).toBe('drag');
  await settings.getByRole('button', {name:'Dictionary', exact:true}).click();
  await settings.getByRole('button', {name:'Add new', exact:true}).click();
  await settings.getByRole('textbox', {name:'New term', exact:true}).fill('Electron draft');
  await settings.getByRole('dialog', {name:'Add term', exact:true}).getByRole('button', {name:'Apply', exact:true}).click();
  await expect(settings.getByRole('dialog', {name:'Add term', exact:true})).toBeHidden();
  await settings.getByRole('button', {name:'Close window', exact:true}).click();
  await expect(settings.getByRole('dialog', {name:'Unsaved changes', exact:true})).toBeVisible();
  await settings.getByRole('button', {name:'Keep editing', exact:true}).click();
  await expect(settings.locator('[role=dialog]')).toHaveCount(0);
  await settings.screenshot({path:join(evidence, 'settings-draft.png')});
  await settings.getByRole('button', {name:'Close window', exact:true}).click();
  await settings.getByRole('button', {name:'Discard all', exact:true}).click();
  await expect.poll(() => messages.filter(message => message.event === 'settings-hidden').length).toBe(1);
  send({window:'settings-show'});
  await settings.getByRole('button', {name:'Add new', exact:true}).click();
  await settings.getByRole('textbox', {name:'New term', exact:true}).fill('Second draft');
  await settings.getByRole('dialog', {name:'Add term', exact:true}).getByRole('button', {name:'Apply', exact:true}).click();
  await expect(settings.getByRole('dialog', {name:'Add term', exact:true})).toBeHidden();
  await settings.getByRole('button', {name:'Close window', exact:true}).click();
  await expect(settings.getByRole('dialog', {name:'Unsaved changes', exact:true})).toBeVisible();
  await settings.getByRole('button', {name:'Discard all', exact:true}).click();
  const initial = {surface:'idle', status:'', result:'', busy:false, recording:false, uiLanguage:'en', language:'auto', completionId:'', recordingShortcut:'Alt+L', levels:[], translationOptions:[], dictationWritingStyle:'natural', writingStyleRefinementAllowed:true, microphoneDevices:[{id:'default',label:'System default'},{id:'usb',label:'USB microphone'}],quickMicrophoneId:'default',textActions:[{id:'rewrite',name:'Rewrite',enabled:true}]};
  const state = async (name, patch) => {
    send({event:'workflow', state:{...initial,...patch}});
    await expect(pill.locator('.workflow-pill')).toHaveAttribute('data-surface', patch.surface || 'idle');
    await pill.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
    send({window:'pill-show'});
    await pill.locator('.workflow-pill').evaluate(async node => {
      await Promise.all(node.getAnimations({subtree:true}).filter(animation => animation instanceof CSSTransition && ['width', 'height', 'opacity', 'translate', 'border-color'].includes(animation.transitionProperty)).map(animation => animation.finished.catch(() => {})));
    });
    if (patch.feedbackTitle) await expect(pill.getByRole('status')).toHaveText(patch.feedbackTitle);
    await expect.poll(() => pill.evaluate(() => document.documentElement.classList.contains('pill-surface'))).toBe(true);
    await pill.screenshot({path:join(evidence, name + '.png'), omitBackground:true});
  };
  const hoverDock = async () => {
    let rect = await pill.locator('.workflow-pill').boundingBox();
    if (process.platform === 'win32') {
      const bounds = await nativeInput({action:'bounds'}), viewport = await pill.evaluate(() => ({width:innerWidth,height:innerHeight}));
      await nativeInput({action:'move',x:bounds.x+2,y:bounds.y+2});
      await new Promise(resolve => setTimeout(resolve,60));
      await pill.locator('.workflow-pill').evaluate(async node => {
        await Promise.all(node.getAnimations().filter(animation => animation instanceof CSSTransition && ['width', 'height'].includes(animation.transitionProperty)).map(animation => animation.finished.catch(() => {})));
      });
      rect = await pill.locator('.workflow-pill').boundingBox();
      await nativeInput({action:'move',x:bounds.x+(rect.x+rect.width/2)*bounds.width/viewport.width,y:bounds.y+(rect.y+rect.height/2)*bounds.height/viewport.height});
    } else await pill.mouse.move(rect.x+rect.width/2,rect.y+rect.height/2);
    await expect(pill.locator('.workflow-pill')).toHaveAttribute('data-collapsed','false');
    await expect.poll(() => pill.locator('.workflow-pill').evaluate(node => Math.round(node.getBoundingClientRect().width))).toBe(112);
  };
  await state('idle', {});
  send({window:'pill-hide'});
  await expect(pill.locator('.workflow-pill')).toHaveAttribute('data-collapsed','true');
  await expect(pill.getByRole('button', {name:'Start recording',exact:true})).toHaveCount(0);
  await pill.screenshot({path:join(evidence,'dock-collapsed.png'),omitBackground:true});
  await hoverDock();
  const idleBounds = await pill.locator('.workflow-pill').boundingBox();
  expect(idleBounds.width).toBeLessThan(140);
  await expect(pill.getByText('Ready to capture your voice', {exact:true})).toHaveCount(0);
  send({window:'pill-toggle'});
  await expect(pill.locator('.workflow-pill')).toHaveAttribute('data-collapsed','true');
  send({window:'pill-toggle'});
  await expect(pill.locator('.workflow-pill')).toHaveAttribute('data-collapsed','false');
  if (process.platform === 'win32') {
    const nativePresses=[];
    nativePassiveCheck = async phase => {
      await settings.bringToFront();
      await nativeInput({action:'focusTarget'});
      for (const [label,menu] of [['More options','.pill-menu'],['Output language','.pill-language-menu']]) {
        const button=pill.getByRole('button',{name:label,exact:true});
        const aim=async()=>{
          await hoverDock();
          const bounds=await nativeInput({action:'bounds'}), rect=await button.boundingBox();
          const viewport=await pill.evaluate(()=>({width:innerWidth,height:innerHeight}));
          await nativeInput({action:'move',x:bounds.x+(rect.x+rect.width/2)*bounds.width/viewport.width,y:bounds.y+(rect.y+rect.height/2)*bounds.height/viewport.height});
          await expect.poll(async()=>(await nativeInput({action:'bounds'})).receives).toBe(true);
        };
        await pill.evaluate(()=>{
          const events=[]; const listener=event=>events.push({type:event.type,label:event.target.closest?.('button')?.getAttribute('aria-label'),tag:event.target.tagName,x:event.clientX,y:event.clientY});
          for(const type of ['pointerdown','pointerup','click'])document.addEventListener(type,listener,true);
          window.__nativePillProbe={events,dispose:()=>{for(const type of ['pointerdown','pointerup','click'])document.removeEventListener(type,listener,true);}};
        });
        try {
          for(const outside of [true,false]) {
            await pill.evaluate(()=>{window.__nativePillProbe.events.length=0;});
            await aim();const before=await nativeInput({action:'bounds'});expect(before.foreground).toBe(false);
            let during,moved;
            await nativeInput({action:'down'});
            try {
              await expect.poll(async()=>(await nativeInput({action:'bounds'})).capture).toBe(true);
              during=await nativeInput({action:'bounds'});expect(during.foregroundHwnd).toBe(before.foregroundHwnd);
              if(outside) {
                await nativeInput({action:'move',x:before.x+before.width+40,y:before.y+10});
                moved=await nativeInput({action:'bounds'});expect(moved.outside).toBe(true);expect(moved.capture).toBe(true);expect(moved.foregroundHwnd).toBe(before.foregroundHwnd);
              }
            } finally {await nativeInput({action:'up'});}
            await expect.poll(async()=>(await nativeInput({action:'bounds'})).capture).toBe(false);
            const after=await nativeInput({action:'bounds'});expect(after.foregroundHwnd).toBe(before.foregroundHwnd);
            await expect.poll(()=>pill.evaluate(()=>window.__nativePillProbe.events.filter(event=>event.type==='pointerup').length)).toBe(1);
            const events=await pill.evaluate(()=>window.__nativePillProbe.events);
            nativePresses.push({phase,label,outside,before,during,moved,after,events});
            await writeFile(join(evidence,'native-passive-presses.json'),JSON.stringify(nativePresses,null,2));
            expect(events.filter(event=>event.type==='pointerdown')).toHaveLength(1);
            expect(events.filter(event=>event.type==='click' && event.label===label)).toHaveLength(outside?0:1);
            await expect(pill.locator(menu)).toHaveCount(outside?0:1);
          }
          // Close the tested menu without changing focus or invoking an item.
          await aim();await nativeInput({action:'down'});await nativeInput({action:'up'});
          await expect(pill.locator(menu)).toHaveCount(0);
        } finally {await pill.evaluate(()=>{window.__nativePillProbe.dispose();delete window.__nativePillProbe;});}
      }
    };
    await nativePassiveCheck('fresh');
    const fixed = await nativeInput({action:'bounds'});
    await nativeInput({action:'move',x:fixed.x+fixed.width/2,y:fixed.y+fixed.height-2});
    await expect(pill.locator('.workflow-pill')).toHaveAttribute('data-collapsed','false');
    const hoverChanges = await pill.locator('.workflow-pill').evaluate(node => new Promise(resolve => {
      const changes = [], observer = new MutationObserver(() => changes.push(node.getAttribute('data-collapsed')));
      observer.observe(node, {attributes:true,attributeFilter:['data-collapsed']});
      setTimeout(() => {observer.disconnect(); resolve(changes);}, 1000);
    }));
    expect(hoverChanges).toEqual([]);
    await nativeInput({action:'move',x:fixed.x+2,y:fixed.y+2});
    await expect(pill.locator('.workflow-pill')).toHaveAttribute('data-collapsed','true');
    await hoverDock();
    const fixedRect = await pill.locator('.workflow-pill').boundingBox(), fixedViewport = await pill.evaluate(() => ({width:innerWidth,height:innerHeight}));
    const x = fixed.x + (fixedRect.x+fixedRect.width/2)*fixed.width/fixedViewport.width, y = fixed.y+(fixedRect.y+2)*fixed.height/fixedViewport.height;
    await nativeInput({action:'move',x,y}); await nativeInput({action:'down'});
    try { await nativeInput({action:'move',x:x+50,y:y-30}); } finally { await nativeInput({action:'up'}); }
    const after = await nativeInput({action:'bounds'});
    expect({x:after.x,y:after.y}).toEqual({x:fixed.x,y:fixed.y});
    await hoverDock();
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
  const waveInsets = await pill.locator('.workflow-pill').evaluate(node => {
    const bounds = node.getBoundingClientRect();
    return Array.from(node.querySelectorAll('.pill-meter i')).map(bar => { const rect = bar.getBoundingClientRect(); return {top:rect.top-bounds.top,bottom:bounds.bottom-rect.bottom}; });
  });
  expect(waveInsets.every(inset => inset.top >= 6 && inset.bottom >= 6)).toBe(true);
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
  await expect(pill.locator('.pill-typing')).toBeVisible();
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
  await state('passive-return', {});
  if (process.platform === 'win32') await nativePassiveCheck('panel-to-idle');
  if (process.platform === 'win32') await nativeInput({action:'releaseTarget'});
  await state('done', {completionId:'workflow:8',writingStyleFinished:true,writingStyleApplied:false,feedbackOperationId:8});
  await expect(pill.locator('.pill-done-layer')).toHaveAttribute('data-visible','true');
  await expect(pill.getByRole('status')).toHaveText('Done');
  await expect(pill.locator('.workflow-pill')).toHaveAttribute('data-done','false');
  send({event:'workflow',state:{...initial,completionId:'workflow:8',writingStyleFinished:true,feedbackOperationId:8}});
  await expect(pill.locator('.workflow-pill')).toHaveAttribute('data-done','false');
  await state('second-done', {completionId:'workflow:9'});
  await expect(pill.locator('.pill-done-layer')).toHaveAttribute('data-visible','true');
  await state('done-interrupted', {surface:'processing',busy:true});
  await expect(pill.locator('.pill-done-layer')).toHaveAttribute('data-visible','false');
  await state('done-return', {});
  send({window:'pill-hide'});
  await expect(pill.locator('.workflow-pill')).toHaveAttribute('data-collapsed','true');
  await expect(pill.locator('.dock-handle')).toBeVisible();
  await state('idle-menu', {});
  await pill.getByRole('button', {name:'More options',exact:true}).click();
  await expect(pill.getByRole('button', {name:'Tone',exact:true})).toHaveCount(0);
  await expect(pill.getByRole('button', {name:'Quit',exact:true})).toHaveCount(0);
  const quick = pill.locator('.pill-quick-menu');
  await expect(quick.locator('.pill-submenu-chevron')).toHaveCount(2);
  await quick.getByRole('button', {name:'Microphone',exact:true}).hover();
  const microphones = pill.getByRole('menu', {name:'Microphone',exact:true});
  await expect(microphones).toBeVisible();
  send({event:'workflow',state:{...initial,microphoneInventoryBusy:true}});
  await expect(microphones.getByRole('menuitemradio').first()).toBeDisabled();
  await quick.getByRole('button', {name:'Microphone',exact:true}).focus();
  await quick.getByRole('button', {name:'Microphone',exact:true}).press('ArrowRight');
  send({event:'workflow',state:initial});
  await expect(microphones.getByRole('menuitemradio').first()).toBeFocused();
  await microphones.getByRole('menuitemradio', {name:'System default',exact:true}).hover();
  await expect(microphones.getByRole('menuitemradio', {name:'System default',exact:true})).toHaveAttribute('aria-checked','true');
  await microphones.getByRole('menuitemradio', {name:'USB microphone',exact:true}).click();
  await expect.poll(() => messages.some(message => message.method === 'selectQuickMicrophone' && message.args[0] === 'usb')).toBe(true);
  await pill.getByRole('button', {name:'More options',exact:true}).click();
  await quick.getByRole('button', {name:'Text actions',exact:true}).hover();
  const actionsMenu = pill.getByRole('menu', {name:'Text actions',exact:true});
  await expect(actionsMenu).toBeVisible();
  await actionsMenu.getByRole('menuitem', {name:'Rewrite',exact:true}).click();
  await expect.poll(() => messages.some(message => message.method === 'runTextAction' && message.args[0] === 'rewrite')).toBe(true);
  await pill.getByRole('button', {name:'More options',exact:true}).click();
  await pill.screenshot({path:join(evidence,'idle-menu.png'), omitBackground:true});
  await pill.getByRole('button', {name:'Transcribe files',exact:true}).click();
  await expect.poll(() => messages.some(message => message.method === 'openFiles')).toBe(true);
  await pill.getByRole('button', {name:'Output language',exact:true}).click();
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
    expect(bounds.map(rect => rect.height)).toEqual([36,36,36]);
    expect(bounds[1].y).toBe(bounds[0].y); expect(bounds[2].y).toBe(bounds[0].y);
  }
  await dpiSession.send('Emulation.clearDeviceMetricsOverride'); await dpiSession.detach();
  send({event:'workflow',state:initial});
  await expect(pill.locator('.pill-idle')).toBeVisible();
  await pill.getByRole('button', {name:'More options',exact:true}).click();
  await expect(pill.getByRole('button', {name:'Quit',exact:true})).toHaveCount(0);
  for (const page of [settings,pill]) expect(await page.evaluate(() => typeof window.require)).toBe('undefined');
  const native = {transport:'real stdin/stdout pipes', renderer:'packaged Chromium over CDP'};
  expect(rendererErrors).toEqual([]);
  const closed = new Promise(resolve => hostProcess.once('exit',resolve)); hostProcess.stdin.end(); await closed;
  await writeFile(join(evidence,'result.json'), JSON.stringify({native,messages,rendererErrors,errors},null,2));
  console.log('PASS: packaged Electron Settings draft/reopen, pill commands and states, isolated renderer, EOF shutdown. Evidence: ' + evidence);
} finally {
  await writeFile(join(evidence,'diagnostics.json'), JSON.stringify({messages,errors},null,2));
  console.log('Electron evidence: ' + evidence);
  if (process.platform === 'win32' && nativeInput && fixture && fixture.exitCode === null) await nativeInput({action:'releaseTarget'}).catch(()=>{});
  hostProcess?.kill(); fixture?.kill();
  await app?.close().catch(() => {});
  // Keep captures and diagnostics; remove only the isolated runtime profile.
  await environment.dispose();
}
