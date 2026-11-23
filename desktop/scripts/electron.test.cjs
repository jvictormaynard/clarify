'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {PassThrough, Writable} = require('node:stream');
const {EventEmitter, once} = require('node:events');
const {mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {runInNewContext} = require('node:vm');
const {join, resolve} = require('node:path');
const {Bridge, MAX_FRAME, validateRequest} = require('../electron/bridge.cjs');
const {startHost} = require('../electron/host.cjs');

test('Electron startup handles a diagnostic write after the parent pipe closes', async () => {
  const stderr = new Writable({
    write(_chunk, _encoding, callback) {
      callback(Object.assign(new Error('write EPIPE'), {code: 'EPIPE'}));
    },
  });
  const closed = new Promise(resolve => stderr.on('close', resolve));
  const log = () => {};
  runInNewContext(readFileSync(resolve(__dirname, '../electron/main.cjs'), 'utf8'), {
    process: {platform: 'darwin', env: {}, stderr},
    console: {error: log},
    require(name) {
      if (name === 'electron') return {};
      assert.equal(name, './host.cjs');
      return {startHost: async () => { stderr.write('Renderer exited\n'); }};
    },
  });
  await closed;
});

test('JSON lines preserve split UTF-8, route concurrent replies and fail calls on EOF', async () => {
  const input = new PassThrough(), output = new PassThrough(); let sent = ''; output.on('data', c => sent += c);
  const events = []; let ended = false;
  const bridge = new Bridge(input, output, m => events.push(m), () => ended = true);
  assert.doesNotThrow(() => validateRequest('settings', 'recordingRecovery', ['reprocess', 'a'.repeat(32) + '.wav']));
  const first = bridge.call('settings', 'snapshot', []), second = bridge.call('workflow', 'openFiles', []);
  const frame = Buffer.from('{"id":1,"result":"ação"}\n');
  input.write(frame.subarray(0, 24)); input.write(frame.subarray(24));
  input.write('{"id":2,"error":"rejected"}\n{"event":"workflow","state":{"surface":"idle"}}\n');
  assert.equal(await first, 'ação'); await assert.rejects(second, /rejected/);
  assert.deepEqual(JSON.parse(sent.split('\n')[1]), {id: 2, channel: 'workflow', method: 'openFiles', args: []});
  assert.equal(events[0].state.surface, 'idle');
  const pending = bridge.call('settings', 'snapshot', []); input.end();
  await assert.rejects(pending, /disconnected/); assert.equal(ended, true); assert.equal(bridge.pending.size, 0);
});
test('bridge bounds frames, arguments and call lifetime', async () => {
  for (const value of [['workflow','eval',[]], ['settings','constructor',[]], ['settings','setApplicationWritingStyle',['C:\\Apps\\Editor.exe','formal']], ['shell','snapshot',[]], ['workflow','chooseTranslation',[9]], ['workflow','dismissFeedback',['2']], ['workflow','quit',[1]]]) assert.throws(() => validateRequest(...value));
  const input = new PassThrough(), output = new PassThrough(); output.resume(); let ended = false;
  const bridge = new Bridge(input, output, () => {}, () => ended = true, 5);
  await assert.rejects(bridge.call('settings', 'snapshot', []), /did not respond/);
  input.write(Buffer.alloc(MAX_FRAME + 1, 32)); assert.equal(ended, true);
});
function fakeElectron() {
  let contentsID = 0;
  const created = [];
  const handlers = {}, app = new EventEmitter(); app.whenReady = async () => {}; app.quit = () => { app.quits = (app.quits || 0) + 1; };
  app.setActivationPolicy = policy => { app.activationPolicy = policy; };
  class Window extends EventEmitter {
    constructor(options) { super(); created.push(this); this.options = options; this.focusable = options.focusable; this.messages = []; this.webContents = new EventEmitter();
      Object.assign(this.webContents, {id: ++contentsID, mainFrame: {url: ''}, send: (topic, value, target) => this.messages.push(target === undefined ? {topic,value} : {topic,value,target}), setWindowOpenHandler: fn => this.open = fn, forcefullyCrashRenderer: () => this.emit('watchdog-crash')}); }
    loadURL(url) { this.webContents.mainFrame.url = url; return Promise.resolve(); }
    isDestroyed() { return false; } removeMenu() {} setPosition(x, y) { this.position = {x, y}; } setAlwaysOnTop() {}
    destroy() { this.hide(); this.destroyed = true; }
    minimize() { this.minimized = true; this.focused = false; }
    restore() { this.minimized = false; }
    isMinimized() { return !!this.minimized; }
    isMaximized() { return !!this.maximized; }
    focus() { this.focused = true; }
    getNormalBounds() { return this.getBounds(); }
    setMinimumSize(width, height) { this.minimumSize = [width, height]; }
    getBounds() { return {...(this.position || {x: this.options.x ?? 0, y: this.options.y ?? 0}), width: this.options.width, height: this.options.height}; }
    getContentBounds() { return this.getBounds(); }
    setBounds(bounds) { this.position = {x:bounds.x, y:bounds.y}; this.options.width=bounds.width; this.options.height=bounds.height; }
    show() { this.visible = true; } showInactive() { this.inactive = true; this.visible = true; } hide() { this.visible = false; this.focused = false; }
    close() {
      let prevented = false;
      this.emit('close', {preventDefault() { prevented = true; }});
      assert.equal(prevented, true, 'the native close event must retain the renderer');
    }
    isVisible() { return !!this.visible; }
    isFocused() { return !!this.focused; }
    setIgnoreMouseEvents(value) { this.ignores = value; }
    setFocusable(value) { this.focusable = value; }
    setVisibleOnAllWorkspaces(visible, options) { this.workspaces = {visible, options}; }
    getNativeWindowHandle() { return Buffer.alloc(8); }
  }
  return {passiveWindow: {changes: [], setPassive(_handle, value) {this.changes.push(value);}}, app, BrowserWindow: Window, ipcMain: {handle: (key, fn) => handlers[key] = fn, on: (key, fn) => handlers[key] = fn}, handlers, created,
    screen: {events:{}, on(name, callback) {this.events[name]=callback;}, reads: 0, cursor: {x:100,y:100}, getCursorScreenPoint() { this.reads++; return this.cursor; }, getPrimaryDisplay: () => ({workArea: {x:0,y:0,width:1920,height:1080}}), getDisplayNearestPoint() {return this.getPrimaryDisplay();}, getDisplayMatching() {return this.getPrimaryDisplay();}},
    session: {defaultSession: {
      setPermissionRequestHandler(fn) { handlers.permission = fn; },
      setPermissionCheckHandler(fn) { handlers.permissionCheck = fn; },
      setDisplayMediaRequestHandler(fn) { handlers.display = fn; },
      webRequest: {onBeforeRequest(fn) { handlers.content = fn; }}
    }}};
}
test('macOS permission guide starts a native app drag and closes when access is confirmed', async t => {
  const directory = mkdtempSync(join(tmpdir(), 'clarify-permission-guide-'));
  t.after(() => rmSync(directory, {recursive: true, force: true}));
  const bundle = join(directory, 'Clarify.app'), contents = join(bundle, 'Contents');
  mkdirSync(join(contents, 'MacOS'), {recursive: true});
  writeFileSync(join(contents, 'MacOS/Clarify'), '');
  const e = fakeElectron(), input = new PassThrough(), output = new PassThrough();
  e.app.isPackaged = true;
  e.app.getPath = key => {
    assert.equal(key, 'exe');
    return join(contents, 'Helpers/Clarify Desktop.app/Contents/MacOS/Clarify Desktop');
  };
  const icon = {isEmpty: () => false};
  e.nativeImage = {createFromPath: () => ({resize: () => icon})};
  const {windows, bridge} = await startHost(e, input, output, null, 'darwin', null,
    () => ({x: 20, y: 40, width: 800, height: 600}));
  t.after(() => bridge.end());
  const event = win => ({sender: win.webContents, senderFrame: win.webContents.mainFrame});
  input.write('{"window":"settings-show"}\n');
  e.handlers['clarify:renderer-ready'](event(windows.settings));
  assert.equal(e.handlers['clarify:window'](event(windows.settings), 'canDragInstalledApp'), true);
  // macOS may report the owner as invisible when System Settings covers it.
  windows.settings.visible = false;
  e.handlers['clarify:window'](event(windows.settings), 'showPermissionGuide', {permission: 'accessibility', locale: 'pt'});
  const panel = e.created.at(-1);
  assert.equal(new URL(panel.webContents.mainFrame.url).searchParams.get('locale'), 'pt');
  assert.equal(panel.options.focusable, false);
  panel.emit('ready-to-show');
  assert.equal(panel.inactive, true);
  assert.deepEqual(panel.position, {x: 836, y: 460});
  const dragged = [];
  panel.webContents.startDrag = item => dragged.push(item);
  e.handlers['clarify:drag-installed-app']({...event(panel), senderFrame: {url: panel.webContents.mainFrame.url}});
  e.handlers['clarify:drag-installed-app'](event(panel));
  assert.deepEqual(dragged, [{file: bundle, icon}]);
  input.write(JSON.stringify({event: 'settings', state: {dictationPermissions: {accessibility: 'allowed'}}}) + '\n');
  assert.equal(panel.destroyed, true);
});
test('meeting capture permission is scoped to an admitted recording and the workspace frame', async () => {
  const e = fakeElectron(), input = new PassThrough(), output = new PassThrough();
  const {windows: {settings, pill}, bridge} = await startHost(e, input, output, e.passiveWindow, 'linux');
  const sender = win => ({sender: win.webContents, senderFrame: win.webContents.mainFrame});
  const permit = (win, mediaTypes = ['audio'], isMainFrame = true) => {
    let granted;
    e.handlers.permission(win.webContents, 'media', value => granted = value, {
      isMainFrame, mediaTypes, requestingUrl: win.webContents.mainFrame.url,
    });
    return granted;
  };
  try {
    assert.equal(permit(settings), false);
    assert.throws(() => e.handlers['clarify:call'](sender(pill), 'meetings', 'get', ['one']), /Invalid renderer channel/);
    assert.throws(() => e.handlers['clarify:call'](sender(settings), 'meetings', 'start', ['one', 'mic']), /capture_unavailable/);
    e.handlers['clarify:renderer-ready'](sender(settings));
    input.write('{"window":"settings-show"}\n');
    const start = e.handlers['clarify:call'](sender(settings), 'meetings', 'start', ['one', 'mic']);
    input.write('{"event":"meetings","state":{"active":{"id":"one","status":"starting"},"captureId":"first"}}\n{"id":1,"result":{"captureId":"first"}}\n');
    await start;
    assert.equal(permit(settings), true);
    assert.equal(permit(settings, ['video']), false);
    assert.equal(permit(settings, ['audio'], false), false);
    assert.equal(permit(pill), false);
    let display;
    e.handlers.display({frame:settings.webContents.mainFrame, audioRequested:true, videoRequested:true, userGesture:true}, value => display = value);
    assert.equal(display, null);
    input.write('{"event":"meetings","state":{"active":{"id":"one","status":"recording"},"captureId":"first"}}\n');
    assert.equal(permit(settings), false);
    e.handlers['clarify:window'](sender(settings), 'meetingAudioReleased', 'first');
    const stale = e.handlers['clarify:call'](sender(settings), 'meetings', 'start', ['one', 'mic']);
    input.write('{"id":2,"result":{"captureId":"stale"}}\n{"event":"meetings","state":{"active":null,"captureId":null}}\n');
    await assert.rejects(stale, /capture_unavailable/);
    assert.equal(permit(settings), false);
  } finally { bridge.end(); }
});
test('early meeting open reaches the workspace with the latest note and dock stop stays scoped', async () => {
  const e = fakeElectron(), input = new PassThrough(), output = new PassThrough();
  const {windows: {settings, pill}, bridge} = await startHost(e, input, output, e.passiveWindow, 'linux');
  const sender = win => ({sender: win.webContents, senderFrame: win.webContents.mainFrame});
  let commands = '';
  output.on('data', data => { commands += data; });
  const windowEvent = 'clarify:window-event';
  try {
    input.write('{"window":"meetings-show"}\n');
    input.write('{"event":"meetings","state":{"active":{"id":"paused-note","status":"paused"}}}\n');
    assert.equal(settings.isVisible(), false);
    e.handlers['clarify:renderer-ready'](sender(settings));
    assert.equal(settings.isFocused(), true);
    assert.deepEqual(settings.messages.at(-1), {topic:windowEvent, value:'meetings', target:'paused-note'});
    assert.throws(() => e.handlers['clarify:window'](sender(pill), 'stopMeeting', 'other-note'), /Invalid pill control/);
    assert.throws(() => e.handlers['clarify:call'](sender(pill), 'meetings', 'stop', ['paused-note']), /Invalid renderer channel/);
    e.handlers['clarify:window'](sender(pill), 'stopMeeting', 'paused-note');
    assert.deepEqual(settings.messages.at(-1), {topic:windowEvent, value:'meeting-stop', target:'paused-note'});
    assert.equal(commands, '');
  } finally { bridge.end(); }
});
test('macOS retains one right-aligned meeting window as the only capture owner', async () => {
  const e = fakeElectron(), input = new PassThrough(), output = new PassThrough();
  const {windows, bridge} = await startHost(e, input, output, e.passiveWindow, 'darwin', null);
  const {settings, pill} = windows;
  const sender = win => ({sender: win.webContents, senderFrame: win.webContents.mainFrame});
  const ready = win => e.handlers['clarify:renderer-ready'](sender(win));
  const command = (win, method, value) => e.handlers['clarify:window'](sender(win), method, value);
  const call = (win, method, args) => e.handlers['clarify:call'](sender(win), 'meetings', method, args);
  const permit = win => {
    let allowed;
    e.handlers.permission(win.webContents, 'media', value => { allowed = value; }, {
      requestingUrl: win.webContents.mainFrame.url, mediaTypes: ['audio'], isMainFrame: true,
    });
    return allowed;
  };
  let sent = '';
  output.on('data', chunk => { sent += chunk; });
  try {
    assert.equal(e.app.activationPolicy, 'accessory');
    ready(settings);
    ready(pill);
    input.write('{"window":"settings-show"}\n');
    assert.equal(e.app.activationPolicy, 'regular');
    assert.equal(settings.options.title, 'Clarify Settings');
    assert.equal(settings.options.skipTaskbar, false);
    command(settings, 'openMeeting', 'note-a');
    const editor = windows.meeting;
    assert.deepEqual(editor.getBounds(), {x: 1380, y: 0, width: 540, height: 820});
    assert.equal(editor.options.alwaysOnTop, false);
    assert.equal(editor.options.skipTaskbar, false);
    assert.equal(editor.options.resizable, true);
    assert.equal(editor.options.title, 'Clarify Meeting');
    assert.equal(editor.isVisible(), false);
    ready(editor);
    assert.equal(editor.isVisible(), true);
    assert.deepEqual(editor.messages.at(-1), {topic: 'clarify:window-event', value: 'meeting-editor', target: 'note-a'});
    for (const method of ['start', 'startWithOverlap', 'feed', 'stop', 'resume']) {
      assert.throws(() => call(settings, method, ['note-a', 'mic']), /Invalid renderer channel/);
    }
    assert.throws(() => call(editor, 'start', ['another-note', 'mic']), /capture_unavailable/);
    const opening = call(editor, 'startWithOverlap', ['note-a', 'system']);
    input.write('{"event":"meetings","state":{"active":{"id":"note-a","status":"starting"},"captureId":"lease"}}\n{"id":1,"result":{"captureId":"lease"}}\n');
    await opening;
    assert.match(sent, /"method":"startWithOverlap"/);
    assert.equal(permit(settings), false);
    assert.equal(permit(pill), false);
    assert.equal(permit(editor), true);
    input.write('{"event":"meetings","state":{"active":{"id":"note-a","status":"recording"},"captureId":"lease"}}\n');
    assert.equal(permit(editor), false);
    command(settings, 'closeAccepted');
    assert.equal(editor.isVisible(), true);
    assert.equal(e.app.activationPolicy, 'regular');
    let prevented = false;
    editor.webContents.emit('before-input-event', {preventDefault: () => { prevented = true; }}, {type:'keyDown', meta:true, key:'w'});
    assert.equal(prevented, true);
    assert.equal(editor.isVisible(), false);
    assert.equal(e.app.activationPolicy, 'accessory');
    call(pill, 'open', []);
    assert.match(sent, /"event":"meetings-open"/);
    input.write('{"window":"meetings-show"}\n');
    assert.equal(windows.meeting, editor);
    assert.equal(editor.isVisible(), true);
    assert.equal(settings.isVisible(), false);
    command(settings, 'openMeeting', 'another-note');
    assert.equal(editor.messages.at(-1).target, 'note-a');
    editor.close();
    command(pill, 'stopMeeting', 'note-a');
    assert.deepEqual(editor.messages.at(-1), {topic: 'clarify:window-event', value: 'meeting-stop', target: 'note-a'});
    assert.doesNotMatch(sent, /"method":"stop"/);
    assert.throws(() => command(settings, 'meetingAudioReleased', 'lease'), /Invalid window control/);
    command(editor, 'meetingAudioReleased', 'lease');
    assert.match(sent, /"event":"meetings-media-released","captureId":"lease"/);
  } finally { bridge.end(); }
});
async function windowsMeetingHost() {
  const e = fakeElectron(), input = new PassThrough(), output = new PassThrough();
  const commands = [];
  output.on('data', data => commands.push(JSON.parse(data)));
  const {windows, bridge} = await startHost(e, input, output, e.passiveWindow, 'win32');
  const sender = win => ({sender: win.webContents, senderFrame: win.webContents.mainFrame});
  const ready = win => e.handlers['clarify:renderer-ready'](sender(win));
  const command = (win, method, value) => e.handlers['clarify:window'](sender(win), method, value);
  const call = (win, method, args) => e.handlers['clarify:call'](sender(win), 'meetings', method, args);
  const send = message => input.write(JSON.stringify(message) + '\n');
  const reply = result => send({id: commands.at(-1).id, result});
  return {...e, windows, bridge, commands, ready, command, call, send, reply, sender};
}

test('Windows puts a resizable meeting editor on the current monitor and restores its active note', async () => {
  const {app, screen, passiveWindow, windows, bridge, commands, ready, command, call, send} = await windowsMeetingHost();
  const {settings, pill} = windows;
  const mainArea = {x: 0, y: 0, width: 1920, height: 1040};
  const leftArea = {x: -1280, y: -140, width: 1280, height: 850};
  const compactArea = {x: 1920, y: 80, width: 360, height: 440};
  const displayAt = point => point.x < 0 ? {workArea: leftArea, scaleFactor: 1.5}
    : point.x >= 1920 ? {workArea: compactArea, scaleFactor: 2} : {workArea: mainArea, scaleFactor: 1};
  screen.getDisplayNearestPoint = displayAt;
  screen.getDisplayMatching = ({x, y, width, height}) => displayAt({x: x + width / 2, y: y + height / 2});
  try {
    ready(settings);
    ready(pill);
    send({window: 'settings-show'});
    settings.setPosition(-1200, -100);
    command(settings, 'openMeeting', 'active-note');
    const editor = windows.meeting;
    assert.deepEqual(editor.getBounds(), {x: -540, y: -140, width: 540, height: 820});
    assert.equal(editor.options.frame, true);
    assert.equal(editor.options.resizable, true);
    assert.equal(editor.options.alwaysOnTop, false);
    assert.equal(editor.options.skipTaskbar, false);
    assert.equal(editor.options.focusable, true);
    assert.equal(editor.webContents.listenerCount('before-input-event'), 0, 'Windows uses the native keyboard controls');
    assert.equal(app.activationPolicy, undefined);
    assert.equal(pill.focusable, false);
    ready(editor);
    send({event: 'meetings', state: {active: {id: 'active-note', status: 'recording'}}});
    const resized = {x: -630, y: -100, width: 590, height: 705};
    editor.setBounds(resized);
    command(settings, 'openMeeting', 'other-note');
    assert.deepEqual(editor.getBounds(), resized);
    assert.equal(editor.messages.at(-1).target, 'active-note');
    command(editor, 'minimize');
    assert.equal(editor.isMinimized(), true);
    assert.equal(editor.isFocused(), false);

    screen.cursor = {x: 2000, y: 100};
    call(pill, 'open', []);
    assert.deepEqual(commands.at(-1), {event: 'meetings-open'});
    send({window: 'meetings-show'});
    assert.equal(windows.meeting, editor);
    assert.equal(editor.isMinimized(), false);
    assert.equal(editor.isFocused(), true);
    assert.deepEqual(editor.getBounds(), compactArea);
    assert.deepEqual(editor.minimumSize, [360, 440]);
    assert.equal(editor.messages.at(-1).target, 'active-note');
    assert.equal(pill.focusable, false);
    assert.deepEqual(passiveWindow.changes, [true]);

    // The native close event is shared by the close button and Alt+F4.
    editor.close();
    assert.equal(editor.isVisible(), false);
    assert.equal(editor.isFocused(), false);
    assert.equal(commands.some(({event, method}) => event === 'quit' || method === 'stop'), false);
    screen.getDisplayMatching = () => ({workArea: mainArea});
    screen.events['display-removed']();
    assert.deepEqual(editor.getBounds(), {x: 1480, y: 80, width: 440, height: 480});
    assert.equal(editor.isVisible(), false);
    command(settings, 'openMeeting', 'other-note');
    assert.equal(windows.meeting, editor);
    assert.equal(editor.messages.at(-1).target, 'active-note');
    editor.close();
    const interruption = {event: 'meetings-interruption-opened', meetingId: 'active-note'};
    send({event: 'meetings', state: {active: null, interruptedId: 'active-note'}});
    assert.equal(editor.isVisible(), false);
    assert.equal(commands.some(({event}) => event === interruption.event), false);
    send({window: 'settings-hide'});
    send({event: 'settings-audio-stop', lease: 'old-recording'});
    assert.equal(settings.isVisible(), false);
    assert.deepEqual(settings.messages.at(-1), {topic: 'clarify:stop-audio', value: 'old-recording'});
    send({window: 'meetings-show'});
    assert.equal(editor.isVisible(), true);
    assert.equal(editor.messages.at(-1).target, 'active-note');
    assert.deepEqual(commands.at(-1), interruption);
  } finally { bridge.end(); }
});

test('Windows grants microphone and loopback only to the detached editor and its current attempt', {timeout: 7000}, async () => {
  const {windows, bridge, handlers, commands, ready, command, call, send, reply} = await windowsMeetingHost();
  const {settings, pill} = windows;
  const permission = (win, kind, overrides = {}) => {
    let allowed;
    handlers.permission(win.webContents, kind, value => { allowed = value; }, {
      requestingUrl: win.webContents.mainFrame.url, mediaTypes: ['audio'], isMainFrame: true, ...overrides,
    });
    return allowed;
  };
  const audio = (win, overrides) => permission(win, 'media', overrides);
  const displayPermission = (win, overrides) => permission(win, 'display-capture', overrides);
  const audioCheck = (win, overrides = {}) => handlers.permissionCheck(win.webContents, 'media', '', {
    isMainFrame: true, mediaType: 'audio', ...overrides,
  });
  const display = (frame, overrides = {}) => {
    let grant;
    handlers.display({frame, userGesture: true, audioRequested: true, videoRequested: true, ...overrides}, value => { grant = value; });
    return grant;
  };
  const capture = (status, source, captureId) => send({
    event: 'meetings', state: {active: {id: 'note', status, source}, captureId},
  });
  try {
    ready(settings);
    ready(pill);
    send({window: 'settings-show'});
    command(settings, 'openMeeting', 'note');
    const editor = windows.meeting;
    const frame = editor.webContents.mainFrame;
    assert.throws(() => call(editor, 'start', ['note', 'system']), /capture_unavailable/);
    ready(editor);
    for (const [method, args] of [['start', ['note', 'mic']], ['resume', ['note']], ['feed', ['note', 'AAE=', false, 'mic']]]) {
      assert.throws(() => call(settings, method, args), /Invalid renderer channel/);
    }
    assert.throws(() => call(editor, 'start', ['other', 'mic']), /capture_unavailable/);
    assert.equal(audio(editor), false);
    assert.equal(displayPermission(editor), false);
    assert.equal(display(frame), null);

    const microphone = call(editor, 'start', ['note', 'mic']);
    assert.throws(() => call(editor, 'start', ['note', 'mic']), /capture_unavailable/);
    capture('starting', 'mic', 'mic-lease');
    reply({captureId: 'mic-lease'});
    await microphone;
    assert.equal(audio(editor), true);
    assert.equal(audioCheck(editor), true);
    assert.equal(audio(settings), false);
    assert.equal(audioCheck(pill), false);
    assert.equal(audio(editor, {mediaTypes: ['audio', 'video']}), false);
    assert.equal(audio(editor, {requestingUrl: settings.webContents.mainFrame.url}), false);
    assert.equal(audio(editor, {isMainFrame: false}), false);
    assert.equal(audioCheck(editor, {mediaType: 'video'}), false);
    assert.equal(displayPermission(editor), false);
    assert.equal(display(frame), null);
    assert.throws(() => call(editor, 'feed', ['note', 'AAE=', false, 'mic-lease']), /capture_unavailable/);
    capture('recording', 'mic', 'mic-lease');
    assert.equal(audio(editor), false);
    editor.close();
    const pcm = call(editor, 'feed', ['note', 'AAE=', false, 'mic-lease']);
    reply(null);
    await pcm;
    const stopped = call(editor, 'stop', ['note']);
    reply(null);
    await stopped;
    command(editor, 'meetingAudioReleased', 'mic-lease');
    send({event: 'meetings', state: {active: null, captureId: null}});

    command(settings, 'openMeeting', 'note');
    const system = call(editor, 'start', ['note', 'system']);
    capture('starting', 'system', 'system-lease');
    reply({captureId: 'system-lease'});
    await system;
    assert.equal(audio(editor), true);
    assert.equal(displayPermission(settings), false);
    assert.equal(displayPermission(editor, {requestingUrl: settings.webContents.mainFrame.url}), false);
    assert.equal(displayPermission(editor, {isMainFrame: false}), false);
    assert.equal(displayPermission(editor), true);
    assert.equal(display(settings.webContents.mainFrame), null);
    assert.equal(display({...frame}), null);
    assert.equal(display(frame, {userGesture: false}), null);
    assert.equal(display(frame, {audioRequested: false}), null);
    assert.equal(display(frame, {videoRequested: false}), null);
    assert.deepEqual(display(frame), {video: frame, audio: 'loopback'});
    assert.equal(display(frame), null, 'only one loopback grant per attempt');
    assert.equal(displayPermission(editor), false);
    capture('recording', 'system', 'system-lease');
    const pause = call(editor, 'pause', ['note']);
    reply(null);
    await pause;
    capture('paused', 'system', null);
    assert.equal(audio(editor), false);
    assert.throws(() => call(editor, 'resume', ['note']), /capture_unavailable/);
    assert.throws(() => command(settings, 'meetingAudioReleased', 'system-lease'), /Invalid window control/);
    command(editor, 'meetingAudioReleased', 'system-lease');
    assert.deepEqual(commands.at(-1), {event: 'meetings-media-released', captureId: 'system-lease'});
    editor.minimize();
    assert.throws(() => call(editor, 'resume', ['note']), /capture_unavailable/);
    send({window: 'meetings-show'});
    assert.throws(() => call(editor, 'resume', ['other']), /capture_unavailable/);
    const resume = call(editor, 'resume', ['note']);
    capture('starting', 'system', 'resume-lease');
    reply({captureId: 'resume-lease'});
    await resume;
    command(editor, 'meetingAudioReleased', 'system-lease');
    assert.equal(audio(editor), true);
    const replacement = {url: frame.url};
    editor.webContents.mainFrame = replacement;
    assert.equal(audio(editor), false);
    assert.equal(displayPermission(editor), false);
    assert.equal(display(replacement), null);
    assert.throws(() => call(editor, 'mediaReady', ['note', 'Fake mic', 'resume-lease']), /capture_unavailable/);
    editor.webContents.mainFrame = frame;
    assert.equal(displayPermission(editor), true);
    assert.deepEqual(display(frame), {video: frame, audio: 'loopback'});
    assert.throws(() => call(editor, 'mediaReady', ['note', 'Fake mic', 'system-lease']), /capture_unavailable/);
    const mediaReady = call(editor, 'mediaReady', ['note', 'Fake mic', 'resume-lease']);
    reply(null);
    await mediaReady;
    capture('recording', 'system', 'resume-lease');
    assert.throws(() => call(editor, 'feedChannels', ['note', 'AAE=', 'AAI=', 'system-lease']), /capture_unavailable/);
    assert.throws(() => call(editor, 'feed', ['note', 'AAE=', true, 'resume-lease']), /capture_unavailable/);
    assert.throws(() => call(editor, 'feedChannels', ['note', 'A'.repeat(13657), 'AAI=', 'resume-lease']), /invalid_audio/);
    const channels = ['note', 'AAE=', 'AAI=', 'resume-lease'];
    const paired = call(editor, 'feedChannels', channels);
    assert.deepEqual(commands.at(-1).args, channels);
    assert.throws(() => call(editor, 'feedChannels', channels), /capture_overload/);
    reply(null);
    await paired;

    editor.close();
    assert.throws(() => command(pill, 'stopMeeting', 'other'), /Invalid pill control/);
    command(pill, 'stopMeeting', 'note');
    assert.deepEqual(editor.messages.at(-1), {topic: 'clarify:window-event', value: 'meeting-stop', target: 'note'});
    assert.equal(editor.isVisible(), false);
    assert.equal(pill.isFocused(), false);
    const stop = call(editor, 'stop', ['note']);
    reply(null);
    await stop;
    const crashed = once(editor, 'watchdog-crash');
    const keepAlive = setTimeout(() => {}, 4000);
    try {
      capture('finalizing', 'system', 'resume-lease');
      await crashed;
    } finally { clearTimeout(keepAlive); }
    assert.equal(audio(editor), false);
    assert.equal(display(frame), null);
  } finally { bridge.end(); }
});
test('the worklet sends no audio during model startup and drains only admitted samples', () => {
  const messages = [];
  let Worklet;
  runInNewContext(readFileSync(resolve(__dirname, '../src/meetings/pcm-worklet.js'), 'utf8'), {
    AudioWorkletProcessor: class { port = {postMessage: message => messages.push(message)}; },
    registerProcessor: (_name, processor) => { Worklet = processor; },
  });
  const capture = new Worklet({});
  const audio = new Float32Array(128).fill(.5);
  const frame = () => capture.process([[audio], []], [[new Float32Array(128)]]);
  for (let n = 0; n < 50; n++) frame();
  assert.deepEqual(messages, []);
  capture.port.onmessage({data:'begin'});
  frame();
  capture.port.onmessage({data:'drain'});
  assert.equal(messages[0].pcm.byteLength, 256);
  assert.equal(messages[0].system, undefined);
  assert.equal(messages[1], 'drained');
  assert.equal(frame(), false);
  messages.length = 0;
  const stalled = new Worklet({processorOptions: {separateSystem: true}});
  const loopback = new Float32Array(128).fill(-.25);
  stalled.port.onmessage({data:'begin'});
  for (let frame = 0; frame < 1100; frame++) {
    if (!stalled.process([[audio], [loopback]], [[new Float32Array(128)]])) break;
  }
  assert.equal(messages[0].pcm.byteLength, messages[0].system.byteLength);
  assert.equal(new Int16Array(messages[0].pcm)[0], 16384);
  assert.equal(new Int16Array(messages[0].system)[0], -8192);
  assert.equal(messages.length, 26);
  assert.equal(messages[25], 'overload');
});

test('macOS pill follows the usable area when entering and leaving fullscreen', async t => {
  t.mock.timers.enable({apis: ['setInterval']});
  const e = fakeElectron(), input = new PassThrough(), output = new PassThrough();
  output.resume();
  const desktop = {x: 0, y: 24, width: 1920, height: 980};
  const display = {id: 42, workArea: desktop};
  e.screen.getPrimaryDisplay = e.screen.getDisplayNearestPoint = () => display;
  let workArea = desktop;
  const {windows: {pill}, bridge} = await startHost(e, input, output, null, 'darwin', id => {
    assert.equal(id, 42);
    return workArea;
  });
  try {
    assert.deepEqual(pill.workspaces, {
      visible: true,
      options: {visibleOnFullScreen: true, skipTransformProcessType: true},
    });
    assert.deepEqual(pill.position, {x: 630, y: 732});
    e.handlers['clarify:renderer-ready']({sender: pill.webContents, senderFrame: pill.webContents.mainFrame});
    workArea = {x: 0, y: 0, width: 1920, height: 1080};
    t.mock.timers.tick(250);
    assert.deepEqual(pill.position, {x: 630, y: 808});
    assert.equal(pill.focused, undefined);
    workArea = desktop;
    t.mock.timers.tick(250);
    assert.deepEqual(pill.position, {x: 630, y: 732});
  } finally {
    bridge.end();
    e.app.emit('before-quit', {preventDefault() {}});
  }
});

test('host retains settings until accepted close, resets each reopen and keeps pill passive', async () => {
  const e = fakeElectron(), input = new PassThrough(), output = new PassThrough(); let sent = ''; output.on('data', c => sent += c);
  const {windows: {settings, pill}, bridge} = await startHost(e, input, output, e.passiveWindow, 'linux');
  const event = win => ({sender: win.webContents, senderFrame: win.webContents.mainFrame});
  let contentResult;
  e.handlers.content({url: 'blob:null/local-audio', webContentsId: settings.webContents.id}, value => contentResult = value);
  assert.equal(contentResult.cancel, false);
  e.handlers.content({url: 'blob:null/local-audio', webContentsId: pill.webContents.id}, value => contentResult = value);
  assert.equal(contentResult.cancel, true);

  e.handlers['clarify:renderer-ready'](event(settings)); e.handlers['clarify:renderer-ready'](event(pill));
  assert.equal(sent, '{"event":"ready"}\n');
  input.write('{"window":"settings-show"}\n{"window":"pill-show"}\n');
  assert.equal(settings.visible, true); assert.equal(pill.inactive, true); assert.equal(pill.focused, undefined);
  assert.equal(pill.options.focusable, false); assert.equal(pill.options.webPreferences.sandbox, true);
  input.write('{"event":"workflow","state":{"surface":"recording"}}\n');
  assert.equal(pill.focusable, false); assert.equal(pill.focused, undefined);
  input.write('{"event":"workflow","state":{"surface":"translation_picker"}}\n');
  assert.equal(pill.focusable, true); assert.equal(pill.focused, true);
  input.write('{"event":"workflow","state":{"surface":"idle"}}\n');
  assert.equal(pill.focusable, false);
  input.write('{"window":"pill-hide"}\n'); assert.equal(pill.visible, true);
  assert.equal(pill.messages.at(-1).value, 'dock-collapse');
  input.write('{"window":"pill-toggle"}\n'); assert.equal(pill.messages.at(-1).value, 'dock-toggle');
  input.write('{"event":"workflow","state":{"surface":"recording"}}\n'); assert.equal(pill.visible, true);
  e.screen.cursor = {x: pill.position.x + 5, y: pill.position.y + 5};
  e.handlers['clarify:window'](event(pill), 'regions', [{x:0,y:0,width:100,height:100}]);
  assert.equal(pill.ignores, false);
  assert.equal(pill.messages.at(-1).value, 'pointer-enter');
  e.screen.cursor = {x:0,y:0}; await new Promise(resolve => setTimeout(resolve, 60));
  assert.equal(pill.ignores, true, 'native cursor restores click-through without a renderer mouse event');
  assert.equal(pill.messages.at(-1).value, 'pointer-leave');
  input.write('{"event":"workflow","state":{"surface":"settings"}}\n'); assert.equal(pill.visible, true);
  input.write('{"event":"workflow","state":{"surface":"idle"}}\n'); assert.equal(pill.visible, true);
  input.write('{"event":"workflow","state":{"surface":"translation_picker"}}\n');
  input.write('{"event":"workflow","state":{"surface":"settings"}}\n');
  const reads = e.screen.reads;
  await new Promise(resolve => setTimeout(resolve, 60));
  assert.ok(e.screen.reads > reads, 'the dock still detects hover with Settings open');
  input.write('{"event":"workflow","state":{"surface":"files"}}\n'); assert.equal(pill.visible, true);
  const style = '{"event":"workflow","state":{"surface":"idle","writingStyleFinished":true,"feedbackOperationId":7,"writingStyleCaption":"Style applied"}}\n';
  input.write(style); assert.equal(pill.visible, true);
  await new Promise(resolve => setTimeout(resolve, 2250));
  assert.equal(pill.visible, true);
  input.write(style); assert.equal(pill.visible, true, 'feedback expiry returns to the dock');
  pill.setPosition(3000,2000);
  e.screen.getDisplayNearestPoint = () => ({workArea: {x: 0, y: 0, width: 1920, height: 1040}});
  e.screen.events['display-metrics-changed']();
  assert.deepEqual(pill.position, {x: 630, y: 768}, 'Windows retains the taskbar inset from the work area');
  e.screen.getDisplayNearestPoint = point => ({workArea: {x: point.x >= 1920 ? 1920 : 0, y:0,width:1920,height:1080}});
  pill.setPosition(2010,500); e.screen.events['display-metrics-changed']();
  assert.deepEqual(pill.position, {x:2550,y:808});
  assert.equal(pill.getBounds().width,660); assert.equal(pill.getBounds().height,272);
  for (const method of ['dragStart', 'dragMove', 'dragEnd']) {
    assert.throws(() => e.handlers['clarify:window'](event(pill), method), /Invalid/);
  }
  assert.throws(() => e.handlers['clarify:window'](event(pill), 'move', {dx: NaN, dy: 0}), /Invalid/);
  let prevented = false; settings.emit('close', {preventDefault: () => prevented = true});
  assert.equal(prevented, true); assert.equal(settings.visible, true); assert.doesNotMatch(sent, /settings-hidden/);
  e.handlers['clarify:window'](event(settings), 'closeAccepted'); assert.equal(settings.visible, false);
  input.write('{"window":"settings-show"}\n');
  assert.equal(settings.messages.at(-1).value, 'reopen');
  assert.throws(() => e.handlers['clarify:window']({...event(settings), senderFrame: {url: 'file:///other'}}, 'closeAccepted'), /Untrusted/);
  assert.throws(() => e.handlers['clarify:call'](event(pill), 'settings', 'snapshot', []), /channel/);
  assert.throws(() => e.handlers['clarify:call'](event(pill), 'settings', 'savePreference', ['setProviderApiKey', ['secret']]), /channel/);
  const preference = e.handlers['clarify:call'](event(pill), 'settings', 'savePreference', ['setLanguage', ['pt']]);
  input.write('{"id":1,"result":{}}\n'); await preference;
  for (const style of ['', 'natural', 'formal', 'casual', 'very_casual', 'informal', 'organized']) {
    const saving = e.handlers['clarify:call'](event(pill), 'settings', 'savePreference', ['setDictationWritingStyle', [style]]);
    const request = JSON.parse(sent.trim().split('\n').at(-1));
    assert.deepEqual(request.args, ['setDictationWritingStyle', [style]]);
    input.write(JSON.stringify({id: request.id, result: {}}) + '\n'); await saving;
  }
  for (const args of [['setDictationWritingStyle', ['unknown']], ['setDictationWritingStyle', ['formal', 'casual']], ['setLanguage', ['unknown']]]) {
    assert.throws(() => e.handlers['clarify:call'](event(pill), 'settings', 'savePreference', args), /channel/);
  }
  const refresh = e.handlers['clarify:call'](event(settings), 'settings', 'refreshLibrary', ['isolated-library-context']);
  const refreshRequest = JSON.parse(sent.trim().split('\n').at(-1));
  assert.deepEqual(refreshRequest, {id: refreshRequest.id, channel: 'settings', method: 'refreshLibrary', args: ['isolated-library-context']});
  input.write(JSON.stringify({id: refreshRequest.id, result: {snippetContext: 'isolated-library-context'}}) + '\n');
  assert.deepEqual(await refresh, {snippetContext: 'isolated-library-context'});
  assert.throws(() => e.handlers['clarify:call'](event(pill), 'settings', 'refreshLibrary', ['isolated-library-context']), /channel/);
  assert.throws(() => e.handlers['clarify:window'](event(pill), 'closeAccepted'), /Invalid/);
  assert.deepEqual(settings.open({url:'https://example.com'}), {action:'deny'});
  e.handlers['clarify:call'](event(pill), 'workflow', 'quit', []); assert.match(sent, /"event":"quit"/);
  bridge.end(); assert.ok(e.app.quits);
});

test('preload exposes the native meeting capability and revokes hidden-window playback before capture', () => {
  for (const [platform, separate] of [['darwin', true], ['win32', true], ['linux', false]]) {
    const handlers = {}, effects = [];
    let api;
    const ipcRenderer = {on: (name, callback) => handlers[name] = callback,
      invoke: async (_channel, _scope, method) => {effects.push(method); return true;}, removeListener() {}};
    runInNewContext(readFileSync(require.resolve('../electron/preload.cjs'), 'utf8'), {
      process: {platform},
      require: () => ({ipcRenderer, contextBridge: {exposeInMainWorld(_key, value) {api = value;}}}),
      CustomEvent: class {constructor(type, options) {this.type=type; this.detail=options.detail;}},
      document: {dispatchEvent: event => effects.push('revoke:' + event.detail), querySelectorAll: () => [{pause: () => effects.push('pause')}]},
    });
    assert.equal(api.separateMeetingWindow, separate);
    handlers['clarify:stop-audio'](null, 'owned-lease');
    assert.deepEqual(effects, ['revoke:owned-lease', 'pause', 'endRecordingPlayback']);
  }
});

const webRTCModule = import('../electron/webrtc-transport.mjs');

class Channel {
  readyState='open'; bufferedAmount=0; sent=[];
  send(value){this.sent.push(value);}
  close(){this.readyState='closed';}
}

test('an uncertain response never repeats the request', async()=>{
  const {ComputerChannel} = await webRTCModule;
  const channel=new Channel();
  const rpc=new ComputerChannel(channel,{timeout:10});
  await assert.rejects(rpc.request({method:'POST',path:'/v1/computer/text',body:{operation_id:'unchanged'}}),/response_uncertain/);
  assert.equal(channel.sent.filter(value=>JSON.parse(value).kind==='begin').length,1);
  assert.equal(rpc.pending.size,0);
  rpc.close();
});

test('out-of-order payload cannot reach dispatch', async()=>{
  const {ComputerChannel} = await webRTCModule;
  const channel=new Channel();let dispatched=0;
  const rpc=new ComputerChannel(channel,{dispatch:()=>{dispatched++;}});
  const id=crypto.randomUUID();
  await rpc.receive(JSON.stringify({kind:'begin',direction:'request',id,count:1}));
  await assert.rejects(rpc.receive(JSON.stringify({kind:'chunk',id,index:1,data:'{}'})),/invalid_chunk/);
  assert.equal(dispatched,0);
  rpc.close();
});

test('cancellation passes a channel with eight waiting processing requests', async()=>{
  const {ComputerChannel} = await webRTCModule;
  const outgoing=new Channel(), incoming=new Channel();
  outgoing.send=value=>queueMicrotask(()=>incoming.onmessage({data:value}));
  incoming.send=value=>queueMicrotask(()=>outgoing.onmessage({data:value}));
  let release, entered, calls=0;
  const blocked=new Promise(resolve=>{release=resolve;});
  const allEntered=new Promise(resolve=>{entered=resolve;});
  const host=new ComputerChannel(incoming,{dispatch:async value=>{
    if(value.method==='DELETE'){release();return {status:200,body:{cancelled:true}};}
    if(++calls===8)entered();
    await blocked;return {status:409,body:{error:'cancelled'}};
  }});
  const client=new ComputerChannel(outgoing);
  try {
    const processing=Array.from({length:8},()=>client.request({method:'POST'}));
    await allEntered;
    await assert.rejects(client.request({method:'POST'}),/capacity/);
    const cancelled=await client.request({method:'DELETE'});
    assert.equal(cancelled.body.cancelled,true);
    assert.equal((await Promise.all(processing)).length,8);
    assert.equal(calls,8);
  } finally { client.close(); host.close(); }
});


test('terminal channel closure retires its owner exactly once and blocks later dispatch', async()=>{
  const {ComputerChannel} = await webRTCModule;
  const channel=new Channel(); let closed=0, dispatched=0;
  const rpc=new ComputerChannel(channel,{onClose:()=>{closed++;},dispatch:()=>{dispatched++;}});
  const pending=rpc.request({method:'POST'});
  channel.onclose(); rpc.close(); channel.onclose();
  await assert.rejects(pending,/response_uncertain/);
  await assert.rejects(rpc.request({method:'POST'}),/response_uncertain/);
  await assert.rejects(rpc.receive('{}'),/response_uncertain/);
  assert.equal(closed,1); assert.equal(dispatched,0);
});
