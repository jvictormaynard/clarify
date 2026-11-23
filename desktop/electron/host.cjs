'use strict';
const path = require('node:path');
const {pathToFileURL, fileURLToPath} = require('node:url');
const {Bridge, validateRequest} = require('./bridge.cjs');

const meetingSize = {width: 540, height: 820};
const meetingMinimum = {width: 440, height: 480};

// Electron work areas and window bounds both use device-independent pixels.
function fitMeeting(area, bounds = meetingSize, alignRight = false) {
  const width = Math.min(area.width, Math.max(bounds.width, meetingMinimum.width));
  const height = Math.min(area.height, Math.max(bounds.height, meetingMinimum.height));
  const right = area.x + area.width - width;
  const bottom = area.y + area.height - height;
  return {
    x: alignRight ? right : Math.max(area.x, Math.min(bounds.x, right)),
    y: alignRight ? area.y : Math.max(area.y, Math.min(bounds.y, bottom)),
    width, height,
  };
}

async function startHost(
  {app, BrowserWindow, ipcMain, screen, session, Tray, Menu, nativeImage, powerMonitor},
  input = process.stdin,
  output = process.stdout,
  passiveWindow = process.platform === 'win32' ? require('./passive_window.node') : null,
  platform = process.platform,
  macWorkArea = process.platform === 'darwin' && platform === 'darwin' ? require('./mac_work_area.node').getWorkArea : null,
) {
  const isMac = platform === 'darwin';
  const isWindows = platform === 'win32';
  const separateMeeting = isMac || isWindows;
  await app.whenReady();
  let stopping = false, settingsPatch = {}, workflowState = null, ready = false;
  const windows = {}, loaded = new Set(), wantsVisible = {settings: false, meeting: false};
  let tray, trayLocale, pillShown = false, pillFocusable = false, hitTimer, interactive = false, regions = [];
  let meetingState, meetingAdmission, meetingMedia, meetingReleaseTimer;
  let meetingDraft = false, quitPending = false, meetingOpenPending = false, meetingTarget;
  let activationPolicy, lastUserSurface = 'settings';
  const captureSurface = separateMeeting ? 'meeting' : 'settings';
  const captureWindow = () => windows[captureSurface];
  const meetingStatus = () => meetingState?.active?.status || (meetingState?.interruptedId ? 'interrupted' : undefined);
  const meetingIndicator = () => ({status: meetingStatus(), id: meetingState?.active?.id});
  let placementTimer;
  const index = path.resolve(__dirname, '../dist/index.html');
  const icon = path.resolve(__dirname, '../icon.png');
  const pageUrl = pathToFileURL(index).href;
  const urls = {settings: pageUrl, pill: pageUrl + '?surface=pill', meeting: pageUrl + '?surface=meeting'};
  const rtc = require('./webrtc-main.cjs').computerWebRTCPipe({BrowserWindow, ipcMain, session}, message => bridge.send(message));
  const stop = () => {
    if (stopping) return;
    stopping = true;
    rtc.stop();
    app.quit();
  };
  const emit = (win, topic, ...args) => { if (loaded.has(win) && !win.isDestroyed()) win.webContents.send(topic, ...args); };
  const hitTest = () => {
    const point = screen.getCursorScreenPoint(), bounds = windows.pill.getContentBounds();
    const x = point.x - bounds.x, y = point.y - bounds.y;
    const hit = regions.some(rect => x >= rect.x && y >= rect.y && x < rect.x + rect.width && y < rect.y + rect.height);
    if (hit !== interactive) {
      interactive = hit; windows.pill.setIgnoreMouseEvents(!hit, {forward: true});
      emit(windows.pill, 'clarify:window-event', hit ? 'pointer-enter' : 'pointer-leave');
    }
  };
  const syncPill = () => {
    const win = windows.pill;
    if (!loaded.has(win) || pillShown) return;
    pillShown = true;
    if (isMac) {
      clampPill();
      // Space and Dock changes can leave Electron's display work area cached.
      placementTimer ??= setInterval(clampPill, 250).unref();
    }
    win.showInactive();
    clearInterval(hitTimer);
    hitTimer = setInterval(hitTest, 25); hitTimer.unref();
  };
  const clampPill = (display) => {
    const win = windows.pill, bounds = win.getBounds();
    display ??= screen.getDisplayNearestPoint({
      x: Math.round(bounds.x + bounds.width / 2),
      y: Math.round(bounds.y + bounds.height / 2),
    });
    const area = macWorkArea?.(display.id) ?? display.workArea;
    const x = Math.round(area.x + (area.width - 660) / 2);
    const y = Math.round(area.y + area.height - 272);
    if (x !== bounds.x || y !== bounds.y || bounds.width !== 660 || bounds.height !== 272) {
      win.setBounds({x, y, width: 660, height: 272});
    }
  };
  const syncActivationPolicy = () => {
    if (!isMac) return;
    const policy = ['settings', 'meeting'].some(surface => wantsVisible[surface] && loaded.has(windows[surface]))
      ? 'regular' : 'accessory';
    if (policy === activationPolicy) return;
    activationPolicy = policy;
    app.setActivationPolicy(policy);
  };
  const resizeMeeting = (win, area, alignRight = false) => {
    const bounds = fitMeeting(area, win.getNormalBounds(), alignRight);
    win.setMinimumSize(Math.min(area.width, meetingMinimum.width), Math.min(area.height, meetingMinimum.height));
    win.setBounds(bounds);
  };
  const showUserWindow = (surface, meetingArea) => {
    wantsVisible[surface] = true;
    const win = windows[surface];
    if (!loaded.has(win)) return;
    lastUserSurface = surface;
    syncActivationPolicy();
    const currentArea = meetingArea && screen.getDisplayMatching(win.getNormalBounds()).workArea;
    const placeMeeting = currentArea && (!win.isVisible() || win.isMinimized()
      || currentArea.x !== meetingArea.x || currentArea.y !== meetingArea.y);
    win.restore();
    if (placeMeeting && !win.isMaximized()) resizeMeeting(win, meetingArea, true);
    win.show();
    win.focus();
  };
  const hideUserWindow = surface => {
    wantsVisible[surface] = false;
    windows[surface].hide();
    syncActivationPolicy();
  };
  const deliverMeetingTarget = () => {
    emit(windows.meeting, 'clarify:window-event', 'meeting-editor', meetingTarget);
  };
  const acknowledgeMeetingInterruption = id => {
    if (id && id === meetingState?.interruptedId) {
      bridge.send({event: 'meetings-interruption-opened', meetingId: id});
    }
  };
  const showMeeting = (id, opener) => {
    meetingTarget = meetingState?.active?.id || meetingAdmission || id;
    const area = isWindows && (opener ? screen.getDisplayMatching(opener.getBounds())
      : screen.getDisplayNearestPoint(screen.getCursorScreenPoint())).workArea;
    if (!windows.meeting) createWindow('meeting', area);
    showUserWindow('meeting', area);
    deliverMeetingTarget();
    acknowledgeMeetingInterruption(meetingTarget);
  };
  const applyWindow = (action) => {
    if (action === 'settings-show' || action === 'meetings-show') {
      if (action === 'meetings-show') {
        meetingOpenPending = true;
        if (!loaded.has(windows.settings)) return;
        if (separateMeeting && (meetingState?.active?.id || meetingState?.interruptedId)) {
          meetingOpenPending = false;
          showMeeting(meetingState.active?.id || meetingState.interruptedId);
          return;
        }
      }
      showUserWindow('settings');
      emit(windows.settings, 'clarify:window-event', 'reopen');
      if (loaded.has(windows.settings) && meetingOpenPending) {
        meetingOpenPending = false;
        const target = meetingState?.active?.id || meetingState?.interruptedId;
        emit(windows.settings, 'clarify:window-event', 'meetings', target);
        acknowledgeMeetingInterruption(target);
      }
    } else if (action === 'settings-hide') {
      // Workflow transitions hide presentation and retain local form drafts.
      // Only a user-confirmed close sends settings-hidden and permits updates.
      hideUserWindow('settings');
    } else if (['pill-show', 'pill-hide', 'pill-toggle'].includes(action)) {
      const presentation = {'pill-show': 'dock-expand', 'pill-hide': 'dock-collapse', 'pill-toggle': 'dock-toggle'};
      emit(windows.pill, 'clarify:window-event', presentation[action]);
      syncPill();
    }
  };
  const requestQuit = () => {
    if (stopping || quitPending) return;
    if (!meetingDraft) { bridge.send({event: 'quit'}); return; }
    quitPending = true;
    if (separateMeeting) showMeeting(meetingTarget);
    else applyWindow('settings-show');
    emit(captureWindow(), 'clarify:window-event', 'meetings-before-quit');
  };
  const bridge = new Bridge(input, output, message => {
    if (rtc.receive(message)) return;
    if (message.event === 'shutdown') { stop(); return; }
    if (message.event === 'settings-audio-stop' && typeof message.lease === 'string') {
      emit(windows.settings, 'clarify:stop-audio', message.lease);
      return;
    }
    if (message.window) { applyWindow(message.window); return; }
    if (message.event === 'meetings' && message.state && typeof message.state === 'object') {
      const previous = meetingIndicator();
      meetingState = message.state;
      if (meetingMedia && (meetingState.captureId !== meetingMedia.captureId || meetingState.active?.status !== 'starting')) {
        meetingMedia.expires = 0;
      }
      emit(windows.settings, 'clarify:state', message);
      emit(windows.meeting, 'clarify:state', message);
      if (meetingMedia && !meetingReleaseTimer && (meetingState.captureId !== meetingMedia.captureId || !['starting', 'recording'].includes(meetingState.active?.status))) {
        // A renderer that cannot release its input must not keep the devices open.
        meetingReleaseTimer = setTimeout(() => captureWindow().webContents.forcefullyCrashRenderer(), 3000);
        meetingReleaseTimer.unref();
      }
      const indicator = meetingIndicator();
      if (previous.status !== indicator.status || previous.id !== indicator.id) {
        emit(windows.pill, 'clarify:state', {event: 'meeting-status', state: indicator});
      }
      return;
    }
    if (message.event === 'settings' && message.state && typeof message.state === 'object') settingsPatch = {...settingsPatch, ...message.state};
    else if (message.event === 'workflow' && message.state && typeof message.state === 'object') {
      const previous = workflowState?.surface;
      workflowState = message.state;
      const panel = ['translation_picker', 'result', 'voice_result', 'voice_error'].includes(workflowState.surface);
      if (panel !== pillFocusable) {
        // Hide the active panel before removing its ability to take focus.
        if (pillFocusable && !panel) { windows.pill.hide(); pillShown = false; clearInterval(hitTimer); hitTimer = undefined; }
        if (panel) passiveWindow?.setPassive(windows.pill.getNativeWindowHandle(), false);
        pillFocusable = panel; windows.pill.setFocusable(panel);
        if (!panel) passiveWindow?.setPassive(windows.pill.getNativeWindowHandle(), true);
      }
      syncPill();
      if (loaded.has(windows.pill) && workflowState.surface === 'translation_picker' && previous !== workflowState.surface) {
        windows.pill.show(); windows.pill.focus();
      }
    }
    else return;
    if (message.event === 'settings') {
      if (message.state.audioPlaybackStopRequest) emit(windows.settings, 'clarify:stop-audio', message.state.audioPlaybackStopRequest);
      emit(windows.settings, 'clarify:state', message);
    }
    else {
      emit(windows.pill, 'clarify:state', message);
      emit(windows.meeting, 'clarify:window-event', 'meeting-locale', workflowState.uiLanguage);
      refreshTray();
    }
  }, stop);
  const ownsMeetingMedia = (frame, id, captureId, status) => Boolean(meetingMedia
    && frame === meetingMedia.frame && id === meetingMedia.id && captureId === meetingMedia.captureId
    && meetingState?.captureId === captureId && meetingState.active?.id === id && meetingState.active.status === status);
  const canCapture = frame => Boolean(frame && frame === captureWindow()?.webContents.mainFrame
    && frame.url === urls[captureSurface] && Date.now() < (meetingMedia?.expires ?? 0)
    && ownsMeetingMedia(frame, meetingMedia.id, meetingMedia.captureId, 'starting'));
  const canCaptureDisplay = frame => isWindows && canCapture(frame)
    && meetingMedia.source === 'system' && !meetingMedia.displayGranted;
  session.defaultSession.setPermissionRequestHandler((wc, permission, callback, details) => {
    if (!wc || wc !== captureWindow()?.webContents || !details.isMainFrame
        || details.requestingUrl !== urls[captureSurface]) {
      callback(false); return;
    }
    // Electron requests display permission before calling the source handler.
    if (permission === 'display-capture') {
      callback(canCaptureDisplay(wc.mainFrame)); return;
    }
    const allowed = permission === 'media' && details.mediaTypes?.length === 1
      && details.mediaTypes[0] === 'audio' && canCapture(wc.mainFrame);
    callback(Boolean(allowed));
  });
  session.defaultSession.setPermissionCheckHandler((wc, permission, _origin, details) => {
    const allowed = wc === captureWindow()?.webContents && permission === 'media' && details.isMainFrame
      && details.mediaType === 'audio' && canCapture(wc.mainFrame);
    return Boolean(allowed);
  });
  session.defaultSession.setDisplayMediaRequestHandler?.((request, callback) => {
    if (!canCaptureDisplay(request.frame) || !request.userGesture || !request.audioRequested || !request.videoRequested) {
      callback(null); return;
    }
    meetingMedia.displayGranted = true;
    // Chromium requires a video track. Restrict it to our own frame and discard
    // that track in the renderer. Only the Windows loopback audio enters ASR.
    callback({video: request.frame, audio: 'loopback'});
  });
  powerMonitor?.on('suspend', () => {
    if (meetingMedia) meetingMedia.expires = 0;
    if (!stopping && !bridge.closed && (meetingState?.active || meetingAdmission)) bridge.send({event: 'meetings-suspended'});
  });
  session.defaultSession.webRequest.onBeforeRequest((details, callback) => {
    // Packaged assets and Settings-owned audio blobs. No network or arbitrary files.
    let allowed = false;
    try {
      const url = new URL(details.url);
      if (url.protocol === 'blob:' && Number.isInteger(details.webContentsId) && details.webContentsId === windows.settings?.webContents.id) {
        allowed = true;
      } else {
        const relative = path.relative(path.resolve(__dirname, '../dist'), fileURLToPath(url));
        allowed = url.protocol === 'file:' && relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative);
      }
    } catch {}
    if (!allowed) process.stderr.write('Blocked content: ' + details.url + '\n');
    callback({cancel: !allowed});
  });
  const createWindow = (surface, meetingArea) => {
    const pill = surface === 'pill';
    const meeting = surface === 'meeting';
    const bounds = meeting ? fitMeeting(meetingArea || screen.getDisplayNearestPoint(screen.getCursorScreenPoint()).workArea, meetingSize, true)
      : {width: pill ? 660 : 1040, height: pill ? 272 : 760};
    const title = meeting ? 'Clarify Meeting' : isMac && !pill ? 'Clarify Settings' : 'Clarify';
    const win = new BrowserWindow({
      title, ...bounds,
      minWidth: Math.min(bounds.width, meeting ? meetingMinimum.width : pill ? 100 : 640),
      minHeight: Math.min(bounds.height, meeting ? meetingMinimum.height : pill ? 50 : 480),
      show: false, frame: meeting, transparent: pill, backgroundColor: pill ? '#00000000' : '#000000',
      alwaysOnTop: pill, skipTaskbar: pill, focusable: !pill, resizable: !pill,
      thickFrame: !pill, hasShadow: !pill,
      icon,
      // A macOS panel can take key focus without activating the app. The
      // passive pill also needs to receive the first click while inactive.
      ...(isMac && pill ? {type: 'panel', acceptFirstMouse: true, enableLargerThanScreen: true} : {}),
      webPreferences: {preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, sandbox: true, nodeIntegration: false, webSecurity: true, backgroundThrottling: false, devTools: false},
    });
    windows[surface] = win;
    if (!isMac) win.removeMenu();
    if (surface === 'settings') for (const event of ['maximize', 'unmaximize']) win.on(event, () => emit(win, 'clarify:window-event', 'resized'));
    if (isMac && !pill) {
      win.on('page-title-updated', event => event.preventDefault());
      win.webContents.on('before-input-event', (event, input) => {
        if (input.type === 'keyDown' && input.meta && !input.control && !input.alt && !input.shift && input.key.toLowerCase() === 'w') {
          event.preventDefault();
          win.close();
        }
      });
    }
    if (pill) {
      if (isMac) {
        // The packaged presentation app is already an LSUIElement.
        win.setVisibleOnAllWorkspaces(true, {visibleOnFullScreen: true, skipTransformProcessType: true});
      }
      clampPill(screen.getPrimaryDisplay());
      win.setIgnoreMouseEvents(true, {forward: true});
      // Keep native mouse capture while preventing activation from stealing the target app.
      passiveWindow?.setPassive(win.getNativeWindowHandle(), true);
      win.setAlwaysOnTop(true, 'pop-up-menu');
    }
    win.webContents.setWindowOpenHandler(() => ({action: 'deny'}));
    win.webContents.on('will-navigate', event => event.preventDefault());
    win.webContents.on('will-attach-webview', event => event.preventDefault());
    win.webContents.on('render-process-gone', (_event, details) => {
      if (stopping) return;
      process.stderr.write('Renderer exited: ' + JSON.stringify(details) + '\n');
      stop();
    });
    win.on('close', event => {
      if (stopping) return;
      event.preventDefault();
      if (meeting) hideUserWindow(surface);
      else if (!pill) emit(win, 'clarify:window-event', 'close');
    });
    void win.loadURL(urls[surface]).catch(error => { process.stderr.write(String(error) + '\n'); stop(); });
  };
  createWindow('settings');
  createWindow('pill');
  syncActivationPolicy();
  const refreshTray = () => {
    if (!tray) return;
    const locale = workflowState?.uiLanguage;
    if (trayLocale === (locale || 'en')) return;
    trayLocale = locale || 'en';
    const text = locale === 'pt' ? ['Configurações', 'Expandir / recolher dock', 'Sair', 'Abrir reuniões'] : locale === 'es' ? ['Configuración', 'Expandir / contraer dock', 'Salir', 'Abrir reuniones'] : ['Settings', 'Expand / collapse dock', 'Quit', 'Open Meetings'];
    const command = method => { void bridge.call('workflow', method, []).catch(error => process.stderr.write(String(error) + '\n')); };
    tray.setContextMenu(Menu.buildFromTemplate([
      {label: text[0], click: () => command('openSettings')},
      {label: text[3], click: () => bridge.send({event: 'meetings-open'})},
      {label: text[1], click: () => command('toggleWindow')},
      {type: 'separator'},
      {label: text[2], click: requestQuit},
    ]));
  };
  if (Tray && Menu) {
    const trayIcon = isMac ? nativeImage.createFromPath(icon).resize({width: 18, height: 18}) : icon;
    tray = new Tray(trayIcon);
    tray.setToolTip('Clarify');
    const command = method => { void bridge.call('workflow', method, []).catch(error => process.stderr.write(String(error) + '\n')); };
    refreshTray();
    tray.on('double-click', () => command('openSettings'));
  }
  for (const event of ['display-metrics-changed', 'display-removed', 'display-added']) screen.on?.(event, () => {
    clampPill();
    const win = windows.meeting;
    if (isWindows && win && !win.isMinimized() && !win.isMaximized()) {
      resizeMeeting(win, screen.getDisplayMatching(win.getNormalBounds()).workArea);
    }
  });
  const sender = event => {
    const surface = Object.keys(windows).find(key => windows[key].webContents === event.sender);
    if (!surface || event.senderFrame !== event.sender.mainFrame || event.senderFrame.url !== urls[surface]) throw new Error('Untrusted renderer');
    return surface;
  };
  ipcMain.handle('clarify:call', (event, channel, method, args) => {
    const surface = sender(event);
    if (channel === 'meetings' && method === 'open' && surface === 'pill' && Array.isArray(args) && !args.length) {
      bridge.send({event: 'meetings-open'});
      return null;
    }
    const pillPreference = surface === 'pill' && channel === 'settings' && method === 'savePreference'
      && Array.isArray(args) && args.length === 2 && Array.isArray(args[1]) && args[1].length === 1
      && ((args[0] === 'setLanguage' && ['auto', 'en', 'pt', 'es', 'de', 'ru'].includes(args[1][0]))
        || (args[0] === 'setDictationWritingStyle' && ['', 'natural', 'formal', 'casual', 'very_casual', 'informal', 'organized'].includes(args[1][0])));
    if (!pillPreference && (surface === 'pill') !== (channel === 'workflow')) throw new Error('Invalid renderer channel');
    if (surface === 'meeting' && channel !== 'meetings') throw new Error('Invalid renderer channel');
    if (separateMeeting && surface === 'settings' && channel === 'meetings' && !['state', 'list', 'create'].includes(method)) {
      throw new Error('Invalid renderer channel');
    }
    validateRequest(channel, method, args);
    if (channel === 'workflow' && method === 'quit') { requestQuit(); return null; }
    if (channel === 'meetings' && ['start', 'startWithOverlap', 'resume'].includes(method)) {
      const owner = captureWindow();
      const id = args[0], frame = event.senderFrame;
      if (typeof id !== 'string' || !id || meetingAdmission || meetingMedia
          || owner.isMinimized() || !owner.isVisible() || !owner.isFocused() || (separateMeeting && id !== meetingTarget)
          || (method === 'resume' && (meetingState?.active?.id !== id || meetingState.active.status !== 'paused'))) {
        throw new Error('capture_unavailable');
      }
      const source = method === 'resume' ? meetingState?.active?.source : args[1];
      meetingAdmission = id;
      return bridge.call(channel, method, args).then(result => {
        const captureId = result?.captureId;
        const admitted = captureId && meetingState?.captureId === captureId
          && meetingState.active?.id === id && meetingState.active.status === 'starting';
        if (!admitted || owner.webContents.mainFrame !== frame || frame.url !== urls[captureSurface]) {
          if (admitted) void bridge.call('meetings', 'interrupt', [id, 'capture_interrupted', captureId]).catch(() => {});
          if (captureId) bridge.send({event: 'meetings-media-released', captureId});
          throw new Error('capture_unavailable');
        }
        meetingMedia = {id, captureId, frame, source, expires: Date.now() + 55000};
        return result;
      }).finally(() => { meetingAdmission = undefined; });
    }
    if (channel === 'meetings' && ['mediaReady', 'feed', 'feedChannels'].includes(method)) {
      const [id, captureId, status] = method === 'mediaReady' ? [args[0], args[2], 'starting'] : [args[0], args[3], 'recording'];
      if (!ownsMeetingMedia(event.senderFrame, id, captureId, status)) throw new Error('capture_unavailable');
      const media = meetingMedia;
      const separate = platform === 'win32' && media.source === 'system';
      if (method !== 'mediaReady' && (method === 'feedChannels') !== separate) throw new Error('capture_unavailable');
      if (method === 'feedChannels') {
        const boundedPcm = value => typeof value === 'string' && value.length > 0 && value.length <= 13656;
        if (args.length !== 4 || !boundedPcm(args[1]) || !boundedPcm(args[2])) throw new Error('invalid_audio');
        if (media.feeding) throw new Error('capture_overload');
        media.feeding = true;
        return bridge.call(channel, method, args).finally(() => { media.feeding = false; });
      }
    }
    return bridge.call(channel, method, args);
  });
  ipcMain.handle('clarify:renderer-ready', event => {
    const surface = sender(event), win = windows[surface]; loaded.add(win);
    if (surface === 'settings' && Object.keys(settingsPatch).length) emit(win, 'clarify:state', {event: 'settings', state: settingsPatch});
    if (surface === 'pill' && workflowState) emit(win, 'clarify:state', {event: 'workflow', state: workflowState});
    if (surface !== 'pill' && meetingState) emit(win, 'clarify:state', {event: 'meetings', state: meetingState});
    if (surface === 'pill' && meetingStatus()) emit(win, 'clarify:state', {event: 'meeting-status', state: meetingIndicator()});
    if (surface === 'settings' && meetingOpenPending) applyWindow('meetings-show');
    else if (surface === 'meeting') {
      emit(win, 'clarify:window-event', 'meeting-locale', workflowState?.uiLanguage);
      if (wantsVisible.meeting) showUserWindow('meeting');
      deliverMeetingTarget();
    }
    else if (wantsVisible[surface]) applyWindow(surface + '-show');
    if (surface === 'pill') syncPill();
    if (loaded.has(windows.settings) && loaded.has(windows.pill) && !ready) { ready = true; bridge.send({event: 'ready'}); }
  });
  ipcMain.handle('clarify:window', (event, method, value) => {
    const surface = sender(event), win = windows[surface];
    if (surface === 'pill') {
      if (method === 'stopMeeting' && typeof value === 'string' && value === meetingState?.active?.id
          && ['recording', 'paused'].includes(meetingState.active.status) && loaded.has(captureWindow())) {
        emit(captureWindow(), 'clarify:window-event', 'meeting-stop', value);
        return;
      }
      if (method === 'regions' && Array.isArray(value) && value.length <= 16 && value.every(rect => rect && ['x', 'y', 'width', 'height'].every(key => typeof rect[key] === 'number' && Number.isFinite(rect[key]) && Math.abs(rect[key]) <= 4096))) {
        regions = value; if (pillShown) hitTest(); return;
      }
      throw new Error('Invalid pill control');
    }
    if (separateMeeting && surface === 'settings' && method === 'openMeeting'
        && typeof value === 'string' && value.length > 0 && value.length <= 80) {
      showMeeting(value, win);
      return;
    }
    if (surface === 'meeting' && method === 'closeMeeting' && typeof value === 'string') {
      if (value === meetingTarget) {
        meetingTarget = undefined;
        win.close();
      }
      return;
    }
    if (surface === 'meeting' && method === 'meetingModels') {
      return bridge.call('workflow', 'openSettings', []).then(() => {
        applyWindow('settings-show');
        emit(windows.settings, 'clarify:window-event', 'meeting-models');
      });
    }
    if (surface !== captureSurface && ['meetingDraft', 'meetingQuitAccepted', 'meetingQuitCancelled', 'meetingAudioReleased'].includes(method)) {
      throw new Error('Invalid window control');
    }
    if (method === 'meetingDraft' && typeof value === 'boolean') {
      if (meetingDraft !== value) bridge.send({event: 'meetings-drafts', pending: value});
      meetingDraft = value;
    }
    else if (method === 'meetingQuitAccepted' && typeof value === 'boolean' && quitPending) {
      if (!value && meetingDraft) throw new Error('Unsaved meeting edits');
      quitPending = false;
      bridge.send({event: 'quit'});
    }
    else if (method === 'meetingQuitCancelled') quitPending = false;
    else if (method === 'meetingAudioReleased' && typeof value === 'string') {
      if (meetingMedia?.captureId === value && meetingMedia.frame === event.senderFrame) {
        meetingMedia = undefined;
        clearTimeout(meetingReleaseTimer);
        meetingReleaseTimer = undefined;
        bridge.send({event: 'meetings-media-released', captureId: value});
      }
    }
    else if (method === 'minimize') win.minimize();
    else if (method === 'toggleMaximize') { win.isMaximized() ? win.unmaximize() : win.maximize(); return win.isMaximized(); }
    else if (method === 'isMaximized') return win.isMaximized();
    else if (method === 'closeAccepted' && surface === 'settings') {
      hideUserWindow('settings');
      bridge.send({event: 'settings-hidden'});
    }
    else throw new Error('Invalid window control');
  });
  if (isMac) app.on('activate', () => {
    if (stopping || bridge.closed) return;
    if (wantsVisible[lastUserSurface]) showUserWindow(lastUserSurface);
    else if (meetingState?.active) showMeeting(meetingState.active.id);
    else void bridge.call('workflow', 'openSettings', []).catch(error => process.stderr.write(String(error) + '\n'));
  });
  app.on('before-quit', event => {
    if (isMac && !stopping) {
      event.preventDefault();
      requestQuit();
      return;
    }
    stopping = true;
    rtc.stop();
    clearInterval(hitTimer);
    clearTimeout(meetingReleaseTimer);
    clearInterval(placementTimer);
    tray?.destroy();
    bridge.end();
  });
  app.on('window-all-closed', stop);
  return {windows, bridge};
}
module.exports = {startHost};
