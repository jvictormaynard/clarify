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
  for (const value of [['workflow','eval',[]], ['settings','constructor',[]], ['shell','snapshot',[]], ['workflow','chooseTranslation',[9]], ['workflow','dismissFeedback',['2']], ['workflow','quit',[1]]]) assert.throws(() => validateRequest(...value));
  const input = new PassThrough(), output = new PassThrough(); output.resume(); let ended = false;
  const bridge = new Bridge(input, output, () => {}, () => ended = true, 5);
  await assert.rejects(bridge.call('settings', 'snapshot', []), /did not respond/);
  input.write(Buffer.alloc(MAX_FRAME + 1, 32)); assert.equal(ended, true);
});
function fakeElectron() {
  const handlers = {}, app = new EventEmitter(); app.whenReady = async () => {}; app.quit = () => { app.quits = (app.quits || 0) + 1; };
  class Window extends EventEmitter {
    constructor(options) { super(); this.options = options; this.focusable = options.focusable; this.messages = []; this.webContents = new EventEmitter();
      Object.assign(this.webContents, {mainFrame: {url: ''}, send: (topic, value) => this.messages.push({topic,value}), setWindowOpenHandler: fn => this.open = fn}); }
    loadURL(url) { this.webContents.mainFrame.url = url; return Promise.resolve(); }
    isDestroyed() { return false; } removeMenu() {} setPosition(x, y) { this.position = {x, y}; } setAlwaysOnTop() {} restore() {} focus() { this.focused = true; }
    getBounds() { return {...(this.position || {x: 0, y: 0}), width: this.options.width, height: this.options.height}; }
    getContentBounds() { return this.getBounds(); }
    setBounds(bounds) { this.position = {x:bounds.x, y:bounds.y}; this.options.width=bounds.width; this.options.height=bounds.height; }
    show() { this.visible = true; } showInactive() { this.inactive = true; this.visible = true; } hide() { this.visible = false; }
    setIgnoreMouseEvents(value) { this.ignores = value; }
    setFocusable(value) { this.focusable = value; }
  }
  return {app, BrowserWindow: Window, ipcMain: {handle: (key, fn) => handlers[key] = fn}, handlers,
    screen: {events:{}, on(name, callback) {this.events[name]=callback;}, reads: 0, cursor: {x:100,y:100}, getCursorScreenPoint() { this.reads++; return this.cursor; }, getPrimaryDisplay: () => ({workArea: {x:0,y:0,width:1920,height:1080}}), getDisplayNearestPoint: () => ({workArea: {x:0,y:0,width:1920,height:1080}})},
    session: {defaultSession: {setPermissionRequestHandler() {}, setPermissionCheckHandler() {}, webRequest: {onBeforeRequest() {}}}}};
}
test('host retains settings until accepted close, resets each reopen and keeps pill passive', async () => {
  const e = fakeElectron(), input = new PassThrough(), output = new PassThrough(); let sent = ''; output.on('data', c => sent += c);
  const {windows: {settings, pill}, bridge} = await startHost(e, input, output);
  const event = win => ({sender: win.webContents, senderFrame: win.webContents.mainFrame});
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
  input.write('{"window":"pill-hide"}\n'); assert.equal(pill.visible, false);
  input.write('{"event":"workflow","state":{"surface":"recording"}}\n'); assert.equal(pill.visible, true);
  e.screen.cursor = {x: pill.position.x + 5, y: pill.position.y + 5};
  e.handlers['clarify:window'](event(pill), 'regions', [{x:0,y:0,width:100,height:100}]);
  assert.equal(pill.ignores, false);
  e.screen.cursor = {x:0,y:0}; await new Promise(resolve => setTimeout(resolve, 60));
  assert.equal(pill.ignores, true, 'native cursor restores click-through without a renderer mouse event');
  input.write('{"event":"workflow","state":{"surface":"settings"}}\n'); assert.equal(pill.visible, false);
  input.write('{"event":"workflow","state":{"surface":"idle"}}\n'); assert.equal(pill.visible, false);
  input.write('{"event":"workflow","state":{"surface":"translation_picker"}}\n');
  input.write('{"event":"workflow","state":{"surface":"settings"}}\n');
  const reads = e.screen.reads;
  await new Promise(resolve => setTimeout(resolve, 60));
  assert.equal(e.screen.reads, reads, 'hidden panel stops native cursor polling');
  const style = '{"event":"workflow","state":{"surface":"idle","writingStyleFinished":true,"feedbackOperationId":7,"writingStyleCaption":"Style applied"}}\n';
  input.write(style); assert.equal(pill.visible, true);
  await new Promise(resolve => setTimeout(resolve, 2250));
  assert.equal(pill.visible, false);
  input.write(style); assert.equal(pill.visible, false, 'unchanged operation does not renew style outcome');
  pill.setPosition(3000,2000);
  e.screen.events['display-metrics-changed']();
  assert.deepEqual(pill.position, {x: 1260, y: 808});
  e.screen.getDisplayNearestPoint = point => ({workArea: {x: point.x >= 1920 ? 1920 : 0, y:0,width:1920,height:1080}});
  pill.setPosition(2010,500); e.screen.events['display-metrics-changed']();
  assert.deepEqual(pill.position, {x:2010,y:500});
  assert.equal(pill.getBounds().width,660); assert.equal(pill.getBounds().height,272);
  const origin={...pill.position}; e.screen.cursor={x:300,y:300};
  e.handlers['clarify:window'](event(pill),'dragStart');
  e.screen.cursor={x:280,y:260};
  for(let sample=0;sample<30;sample++) e.handlers['clarify:window'](event(pill),'dragMove');
  assert.deepEqual(pill.position,{x:origin.x-20,y:origin.y-40});
  e.handlers['clarify:window'](event(pill),'dragStart');
  e.handlers['clarify:window'](event(pill),'regions',[]);
  e.screen.cursor={x:1000,y:1000};e.handlers['clarify:window'](event(pill),'dragMove');
  assert.deepEqual(pill.position,{x:origin.x-20,y:origin.y-40});
  assert.equal(pill.getBounds().width,660);assert.equal(pill.getBounds().height,272);
  e.handlers['clarify:window'](event(pill),'dragEnd');
  e.screen.cursor={x:900,y:900};e.handlers['clarify:window'](event(pill),'dragMove');
  assert.deepEqual(pill.position,{x:origin.x-20,y:origin.y-40});
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
  assert.throws(() => e.handlers['clarify:window'](event(pill), 'closeAccepted'), /Invalid/);
  assert.deepEqual(settings.open({url:'https://example.com'}), {action:'deny'});
  e.handlers['clarify:call'](event(pill), 'workflow', 'quit', []); assert.match(sent, /"event":"quit"/);
  bridge.end(); assert.ok(e.app.quits);
});
