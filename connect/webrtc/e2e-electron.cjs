// Isolated generated-account test. Uses the production main-only private pipe.
const {app} = require('electron');
const {computerWebRTCPipe} = require('../../desktop/electron/webrtc-main.cjs');
const fs = require('node:fs');
const readline = require('node:readline');
const file = process.argv.find(value => value.endsWith('/electron-config.json'));
if (!file?.startsWith('/tmp/')) throw Error('test_config_required');
const config = JSON.parse(fs.readFileSync(file, 'utf8'));
app.disableHardwareAcceleration();
app.whenReady().then(() => {
  const pipe = computerWebRTCPipe(require('electron'), message => {
    process.stdout.write(JSON.stringify(message) + '\n');
    if (message.event === 'computer-webrtc-state' && message.connected) process.stdout.write('READY\n');
  });
  readline.createInterface({input:process.stdin}).on('line', line => pipe.receive(JSON.parse(line)));
  pipe.receive({event:'computer-webrtc-config', config:{host:config.host, privateJwk:config.privateJwk}});
  process.once('SIGTERM', () => { pipe.stop(); app.quit(); });
});
