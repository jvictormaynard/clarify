'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {PassThrough} = require('node:stream');
const {EventEmitter} = require('node:events');
const {Bridge, MAX_FRAME, validateRequest} = require('../electron/bridge.cjs');
const {startHost} = require('../electron/host.cjs');
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
  const handlers = {}, app = new EventEmitter(); app.whenReady = async () => {}; app.quit = () => { app.quits = (app.quits || 0) + 1; };
  class Window extends EventEmitter {
    constructor(options) { super(); this.options = options; this.focusable = options.focusable; this.messages = []; this.webContents = new EventEmitter();
      Object.assign(this.webContents, {id: ++contentsID, mainFrame: {url: ''}, send: (topic, value) => this.messages.push({topic,value}), setWindowOpenHandler: fn => this.open = fn}); }
    loadURL(url) { this.webContents.mainFrame.url = url; return Promise.resolve(); }
    isDestroyed() { return false; } removeMenu() {} setPosition(x, y) { this.position = {x, y}; } setAlwaysOnTop() {} restore() {} focus() { this.focused = true; }
    getBounds() { return {...(this.position || {x: 0, y: 0}), width: this.options.width, height: this.options.height}; }
    getContentBounds() { return this.getBounds(); }
    setBounds(bounds) { this.position = {x:bounds.x, y:bounds.y}; this.options.width=bounds.width; this.options.height=bounds.height; }
    show() { this.visible = true; } showInactive() { this.inactive = true; this.visible = true; } hide() { this.visible = false; }
    setIgnoreMouseEvents(value) { this.ignores = value; }
    setFocusable(value) { this.focusable = value; }
    setVisibleOnAllWorkspaces(visible, options) { this.workspaces = {visible, options}; }
    getNativeWindowHandle() { return Buffer.alloc(8); }
  }
  return {passiveWindow: {setPassive() {}}, app, BrowserWindow: Window, ipcMain: {handle: (key, fn) => handlers[key] = fn}, handlers,
    screen: {events:{}, on(name, callback) {this.events[name]=callback;}, reads: 0, cursor: {x:100,y:100}, getCursorScreenPoint() { this.reads++; return this.cursor; }, getPrimaryDisplay: () => ({workArea: {x:0,y:0,width:1920,height:1080}}), getDisplayNearestPoint: () => ({workArea: {x:0,y:0,width:1920,height:1080}})},
    session: {defaultSession: {setPermissionRequestHandler() {}, setPermissionCheckHandler() {}, webRequest: {onBeforeRequest(fn) { handlers.content = fn; }}}}};
}

test('macOS pill follows the usable area when entering and leaving fullscreen', async t => {
  t.mock.timers.enable({apis: ['setInterval']});
  const e = fakeElectron(), input = new PassThrough(), output = new PassThrough();
  output.resume();
  const desktop = {x: 0, y: 24, width: 1920, height: 980};
  const display = {id: 42, workArea: desktop};
  e.screen.getPrimaryDisplay = e.screen.getDisplayNearestPoint = () => display;
  let workArea = desktop;
  const {windows: {pill}, bridge} = await startHost(e, input, output, null, id => {
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
  const {windows: {settings, pill}, bridge} = await startHost(e, input, output, e.passiveWindow, null);
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

test('preload revokes and pauses hidden-window playback before acknowledging capture', async () => {
  const fs = require('node:fs'), vm = require('node:vm');
  const handlers = {}, effects = [];
  const ipcRenderer = {on: (name, callback) => handlers[name] = callback,
    invoke: async (_channel, _scope, method) => {effects.push(method); return true;}, removeListener() {}};
  vm.runInNewContext(fs.readFileSync(require.resolve('../electron/preload.cjs'), 'utf8'), {
    require: () => ({ipcRenderer, contextBridge: {exposeInMainWorld() {}}}),
    CustomEvent: class {constructor(type, options) {this.type=type; this.detail=options.detail;}},
    document: {dispatchEvent: event => effects.push('revoke:' + event.detail), querySelectorAll: () => [{pause: () => effects.push('pause')}]},
  });
  handlers['clarify:stop-audio'](null, 'owned-lease');
  assert.deepEqual(effects, ['revoke:owned-lease', 'pause', 'endRecordingPlayback']);
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
