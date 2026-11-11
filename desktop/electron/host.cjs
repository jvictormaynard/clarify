'use strict';
const path = require('node:path');
const {pathToFileURL, fileURLToPath} = require('node:url');
const {Bridge, validateRequest} = require('./bridge.cjs');

async function startHost({app, BrowserWindow, ipcMain, screen, session, Tray, Menu}, input = process.stdin, output = process.stdout, passiveWindow = process.platform === 'win32' ? require('./passive_window.node') : null) {
  await app.whenReady();
  let stopping = false, settingsPatch = {}, workflowState = null, ready = false;
  const windows = {}, loaded = new Set(), wantsVisible = {settings: false};
  let tray, trayLocale, pillShown = false, pillFocusable = false, hitTimer, interactive = false, regions = [];
  const index = path.resolve(__dirname, '../dist/index.html');
  const urls = {settings: pathToFileURL(index).href, pill: pathToFileURL(index).href + '?surface=pill'};
  const stop = () => { stopping = true; bridge.end(); app.quit(); };
  const emit = (win, topic, message) => { if (loaded.has(win) && !win.isDestroyed()) win.webContents.send(topic, message); };
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
    win.showInactive();
    clearInterval(hitTimer);
    hitTimer = setInterval(hitTest, 25); hitTimer.unref();
  };
  const clampPill = () => {
    const win = windows.pill, bounds = win.getBounds();
    const {workArea: area} = screen.getDisplayNearestPoint({x: Math.round(bounds.x + bounds.width / 2), y: Math.round(bounds.y + bounds.height)});
    win.setBounds({x: Math.round(area.x + (area.width - 660) / 2), y: area.y + area.height - 272, width: 660, height: 272});
  };
  const applyWindow = (action) => {
    if (action === 'settings-show') {
      wantsVisible.settings = true;
      emit(windows.settings, 'clarify:window-event', 'reopen');
      if (loaded.has(windows.settings)) { windows.settings.restore(); windows.settings.show(); windows.settings.focus(); }
    } else if (action === 'settings-hide') {
      // Workflow transitions hide presentation and retain local form drafts.
      // Only a user-confirmed close sends settings-hidden and permits updates.
      wantsVisible.settings = false;
      windows.settings.hide();
    } else if (['pill-show', 'pill-hide', 'pill-toggle'].includes(action)) {
      const presentation = {'pill-show': 'dock-expand', 'pill-hide': 'dock-collapse', 'pill-toggle': 'dock-toggle'};
      emit(windows.pill, 'clarify:window-event', presentation[action]);
      syncPill();
    }
  };
  const bridge = new Bridge(input, output, message => {
    if (message.event === 'shutdown') { stop(); return; }
    if (message.window) { applyWindow(message.window); return; }
    if (message.event === 'settings' && message.state && typeof message.state === 'object') settingsPatch = {...settingsPatch, ...message.state};
    else if (message.event === 'workflow' && message.state && typeof message.state === 'object') {
      const previous = workflowState?.surface;
      workflowState = message.state;
      const panel = ['translation_picker', 'result', 'voice_result', 'voice_error'].includes(workflowState.surface);
      if (panel !== pillFocusable) {
        // Hide the active picker before removing its activation permission.
        // Windows can then return focus to the previous application.
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
    if (message.event === 'settings') emit(windows.settings, 'clarify:state', message);
    else { emit(windows.pill, 'clarify:state', message); refreshTray(); }
  }, () => { stopping = true; app.quit(); });
  session.defaultSession.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
  session.defaultSession.setPermissionCheckHandler(() => false);
  session.defaultSession.webRequest.onBeforeRequest((details, callback) => {
    // Packaged assets only. No network, arbitrary local files, or external handlers.
    let allowed = false;
    try {
      const url = new URL(details.url);
      const relative = path.relative(path.resolve(__dirname, '../dist'), fileURLToPath(url));
      allowed = url.protocol === 'file:' && relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative);
    } catch {}
    if (!allowed) process.stderr.write('Blocked content: ' + details.url + '\n');
    callback({cancel: !allowed});
  });
  for (const surface of ['settings', 'pill']) {
    const pill = surface === 'pill';
    const win = new BrowserWindow({
      title: 'Clarify', width: pill ? 660 : 1040, height: pill ? 272 : 760,
      minWidth: pill ? 100 : 640, minHeight: pill ? 50 : 480,
      show: false, frame: false, transparent: pill, backgroundColor: pill ? '#00000000' : '#000000',
      alwaysOnTop: pill, skipTaskbar: pill, focusable: !pill, resizable: !pill,
      thickFrame: !pill, hasShadow: !pill,
      icon: path.resolve(__dirname, '../icon.png'),
      webPreferences: {preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, sandbox: true, nodeIntegration: false, webSecurity: true, backgroundThrottling: false, devTools: false},
    });
    windows[surface] = win;
    win.removeMenu();
    if (!pill) for (const event of ['maximize', 'unmaximize']) win.on(event, () => emit(win, 'clarify:window-event', 'resized'));
    if (pill) {
      const {workArea} = screen.getPrimaryDisplay();
      win.setBounds({x:Math.round(workArea.x + (workArea.width - 660) / 2), y:workArea.y + workArea.height - 272, width:660, height:272});
      win.setIgnoreMouseEvents(true, {forward: true});
      // Keep native mouse capture while preventing activation from stealing the target app.
      passiveWindow?.setPassive(win.getNativeWindowHandle(), true);
      win.setAlwaysOnTop(true, 'pop-up-menu');
    }
    win.webContents.setWindowOpenHandler(() => ({action: 'deny'}));
    win.webContents.on('will-navigate', event => event.preventDefault());
    win.webContents.on('will-attach-webview', event => event.preventDefault());
    win.webContents.on('render-process-gone', (_event, details) => { process.stderr.write('Renderer exited: ' + JSON.stringify(details) + '\n'); stop(); });
    win.on('close', event => {
      if (stopping) return;
      event.preventDefault();
      if (!pill) emit(win, 'clarify:window-event', 'close');
    });
    void win.loadURL(urls[surface]).catch(error => { process.stderr.write(String(error) + '\n'); stop(); });
  }
  const refreshTray = () => {
    if (!tray) return;
    const locale = workflowState?.uiLanguage;
    if (trayLocale === (locale || 'en')) return;
    trayLocale = locale || 'en';
    const text = locale === 'pt' ? ['Configurações', 'Expandir / recolher dock', 'Sair'] : locale === 'es' ? ['Configuración', 'Expandir / contraer dock', 'Salir'] : ['Settings', 'Expand / collapse dock', 'Quit'];
    const command = method => { void bridge.call('workflow', method, []).catch(error => process.stderr.write(String(error) + '\n')); };
    tray.setContextMenu(Menu.buildFromTemplate([
      {label: text[0], click: () => command('openSettings')},
      {label: text[1], click: () => command('toggleWindow')},
      {type: 'separator'},
      {label: text[2], click: () => bridge.send({event: 'quit'})},
    ]));
  };
  if (Tray && Menu) {
    tray = new Tray(path.resolve(__dirname, '../icon.png'));
    tray.setToolTip('Clarify');
    const command = method => { void bridge.call('workflow', method, []).catch(error => process.stderr.write(String(error) + '\n')); };
    refreshTray();
    tray.on('double-click', () => command('openSettings'));
  }
  for (const event of ['display-metrics-changed', 'display-removed', 'display-added']) screen.on?.(event, () => clampPill());
  const sender = event => {
    const surface = Object.keys(windows).find(key => windows[key].webContents === event.sender);
    if (!surface || event.senderFrame !== event.sender.mainFrame || event.senderFrame.url !== urls[surface]) throw new Error('Untrusted renderer');
    return surface;
  };
  ipcMain.handle('clarify:call', (event, channel, method, args) => {
    const surface = sender(event);
    const pillPreference = surface === 'pill' && channel === 'settings' && method === 'savePreference'
      && Array.isArray(args) && args.length === 2 && Array.isArray(args[1]) && args[1].length === 1
      && ((args[0] === 'setLanguage' && ['auto', 'en', 'pt', 'es', 'de', 'ru'].includes(args[1][0]))
        || (args[0] === 'setDictationWritingStyle' && ['', 'natural', 'formal', 'casual', 'very_casual', 'informal', 'organized'].includes(args[1][0])));
    if (!pillPreference && (surface === 'pill') !== (channel === 'workflow')) throw new Error('Invalid renderer channel');
    validateRequest(channel, method, args);
    if (channel === 'workflow' && method === 'quit') { bridge.send({event: 'quit'}); return null; }
    return bridge.call(channel, method, args);
  });
  ipcMain.handle('clarify:renderer-ready', event => {
    const surface = sender(event), win = windows[surface]; loaded.add(win);
    if (surface === 'settings' && Object.keys(settingsPatch).length) emit(win, 'clarify:state', {event: 'settings', state: settingsPatch});
    if (surface === 'pill' && workflowState) emit(win, 'clarify:state', {event: 'workflow', state: workflowState});
    if (wantsVisible[surface]) applyWindow(surface + '-show');
    if (surface === 'pill') syncPill();
    if (loaded.size === 2 && !ready) { ready = true; bridge.send({event: 'ready'}); }
  });
  ipcMain.handle('clarify:window', (event, method, value) => {
    const surface = sender(event), win = windows[surface];
    if (surface === 'pill') {
      if (method === 'regions' && Array.isArray(value) && value.length <= 16 && value.every(rect => rect && ['x', 'y', 'width', 'height'].every(key => typeof rect[key] === 'number' && Number.isFinite(rect[key]) && Math.abs(rect[key]) <= 4096))) {
        regions = value; if (pillShown) hitTest(); return;
      }
      throw new Error('Invalid pill control');
    }
    if (method === 'minimize') win.minimize();
    else if (method === 'toggleMaximize') { win.isMaximized() ? win.unmaximize() : win.maximize(); return win.isMaximized(); }
    else if (method === 'isMaximized') return win.isMaximized();
    else if (method === 'closeAccepted') { wantsVisible.settings = false; win.hide(); bridge.send({event: 'settings-hidden'}); }
    else throw new Error('Invalid window control');
  });
  app.on('before-quit', () => { stopping = true; clearInterval(hitTimer); tray?.destroy(); bridge.end(); });
  app.on('window-all-closed', () => stop());
  return {windows, bridge};
}
module.exports = {startHost};
