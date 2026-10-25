// Diagnostic only. Do not integrate this file or its workflow.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createRequire } = require('node:module');
const mode = process.env.CLARIFY_CLOCK_DIAGNOSTIC;
if (!['baseline', 'expire-before-toolbar'].includes(mode)) throw new Error('Unknown diagnostic mode');
const scriptPath = path.resolve('scripts/test-keyboard-ui.cjs');
let script = fs.readFileSync(scriptPath, 'utf8');
const target = 'KeyboardUITests/KeyboardUITests/testErrorCauseFitsTheExistingToolbarWithoutChangingKeyboardHeight';
script = script.replace("'-parallel-testing-enabled', 'NO',", "'-parallel-testing-enabled', 'NO', '-only-testing:" + target + "',");
const anchor = "const support = path.join(fixture, 'Sources/KeyboardHostSupport');";
if (mode === 'expire-before-toolbar') {
  script = script.replace(anchor, `
    const testFile = path.join(tests, 'KeyboardUITests.swift');
    let text = fs.readFileSync(testFile, 'utf8');
    text = text.replace('override var hasFullAccess: Bool { fullAccess }',
      'var onAccessCheck: (() -> Void)?\\n  override var hasFullAccess: Bool { onAccessCheck?(); return fullAccess }');
    text = text.replace('let messages = [', 'var forcedExpiry = false\\n      let messages = [');
    text = text.replace('try store.write(state, to: "state.json"); keyboard.refreshFromStore()', \`
      try store.write(state, to: "state.json")
      var checks = 0
      keyboard.onAccessCheck = {
        checks += 1
        // Three checks precede the label branch. The fourth starts updateToolbar.
        if !forcedExpiry && checks == 4 {
          forcedExpiry = true
          print("CLOCK_DIAGNOSTIC barrier before toolbar fullAccess=\\\\(keyboard.fullAccess) phase=\\\\(state.phase) age=\\\\(Date().timeIntervalSince1970 - state.heartbeat)")
          let deadline = state.heartbeat + 3.025
          while Date().timeIntervalSince1970 < deadline {
            _ = DispatchSemaphore(value: 0).wait(timeout: .now() + max(0, deadline - Date().timeIntervalSince1970))
          }
          print("CLOCK_DIAGNOSTIC barrier released age=\\\\(Date().timeIntervalSince1970 - state.heartbeat)")
        }
      }
      keyboard.refreshFromStore()
      keyboard.onAccessCheck = nil
      print("CLOCK_DIAGNOSTIC refreshed checks=\\\\(checks) fullAccess=\\\\(keyboard.fullAccess) phase=\\\\(store.snapshot().phase) isLive=\\\\(store.snapshot().isLive) detailMatches=\\\\(detail.text == state.message) statusHidden=\\\\(status.isHidden) wrapping=\\\\(detail.lineBreakMode.rawValue)")
    \`);
    fs.writeFileSync(testFile, text);
    ${anchor}
  `);
}
console.log(JSON.stringify({ mode, source: process.env.GITHUB_SHA, target }));
vm.runInThisContext('(function(require){' + script + '\n})', { filename: scriptPath })(createRequire(scriptPath));
