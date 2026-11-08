'use strict';
const MAX_FRAME = 64 * 1024 * 1024;
const workflowMethods = new Set(['startRecordingFromButton', 'stopRecording', 'cancelRecording', 'chooseTranslation', 'cancelTranslation', 'openSettings', 'openFiles', 'showResult', 'copyResult', 'finish', 'reset', 'undoCancellation', 'dismissFeedback', 'retryTranscription', 'pasteLastTranscription', 'toggleWindow', 'quit', 'runTextAction', 'selectQuickMicrophone', 'refreshMicrophones', 'installUpdate']);
// Explicit settings API, shared with the existing Settings client. Python owns validation.
const settingsMethods = new Set(require('./settings-methods.json'));
function validateRequest(channel, method, args) {
  if (!Array.isArray(args) || args.length > 8 || typeof method !== 'string' ||
      !(channel === 'settings' ? settingsMethods : channel === 'workflow' ? workflowMethods : new Set()).has(method)) throw new Error('Invalid bridge request');
  if (channel === 'workflow') {
    if (['chooseTranslation', 'runTextAction', 'selectQuickMicrophone'].includes(method) ? args.length !== 1 || typeof args[0] !== 'string' || args[0].length > 1000 :
      method === 'dismissFeedback' ? args.length !== 1 || !Number.isSafeInteger(args[0]) : args.length !== 0) throw new Error('Invalid workflow arguments');
  }
}
class Bridge {
  constructor(input, output, onMessage, onEnd, timeout = 15000) {
    this.output = output; this.pending = new Map(); this.next = 0; this.closed = false;
    let parts = [], size = 0;
    const end = () => { if (this.closed) return; this.closed = true; for (const p of this.pending.values()) { clearTimeout(p.timer); p.reject(new Error('Clarify disconnected')); } this.pending.clear(); onEnd(); };
    this.end = end;
    input.on('data', chunk => {
      if (this.closed) return;
      const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      let start = 0;
      for (let i = 0; i <= bytes.length; i++) {
        if (i !== bytes.length && bytes[i] !== 10) continue;
        const part = bytes.subarray(start, i); size += part.length;
        if (size > MAX_FRAME) { end(); return; }
        if (part.length) parts.push(part);
        start = i + 1;
        if (i === bytes.length) break;
        let message;
        try { message = JSON.parse(Buffer.concat(parts, size).toString('utf8')); } catch { parts = []; size = 0; continue; }
        parts = []; size = 0;
        if (!message || typeof message !== 'object') continue;
        if (Number.isSafeInteger(message.id)) {
          const pending = this.pending.get(message.id);
          if (pending) { this.pending.delete(message.id); clearTimeout(pending.timer); message.error !== undefined ? pending.reject(new Error(String(message.error))) : pending.resolve(message.result); }
        } else onMessage(message);
      }
    });
    input.on('end', end); input.on('error', end); output.on('error', end);
    this.timeout = timeout;
  }
  send(value) {
    if (this.closed) throw new Error('Clarify disconnected');
    const frame = JSON.stringify(value);
    if (Buffer.byteLength(frame) > MAX_FRAME) throw new Error('Bridge frame too large');
    this.output.write(frame + '\n');
  }
  call(channel, method, args) {
    validateRequest(channel, method, args);
    if (this.closed) return Promise.reject(new Error('Clarify disconnected'));
    const id = ++this.next;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('Clarify did not respond')); }, this.timeout);
      this.pending.set(id, {resolve, reject, timer});
      try { this.send({id, channel, method, args}); } catch (error) { clearTimeout(timer); this.pending.delete(id); reject(error); }
    });
  }
}
module.exports = {Bridge, MAX_FRAME, validateRequest};
