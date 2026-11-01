const fs = require('node:fs');
const path = require('node:path');
const [source, output] = process.argv.slice(2);
if (!source || !output || path.resolve(source) === path.resolve(output)) throw new Error('Separate source and copied fixture paths required.');
let text = fs.readFileSync(source, 'utf8').replace(/\r\n/g, '\n');
function replaceOnce(needle, replacement) {
  if (text.split(needle).length !== 2) throw new Error('Trace source anchor missing or ambiguous: ' + needle.slice(0, 70));
  text = text.replace(needle, replacement);
}
if (path.basename(source) === 'HostActivation.swift') {
  replaceOnce('      let generation = KBHostArbiterHook.captureGeneration()',
    '      let generation = KBHostArbiterHook.captureGeneration()\n      NSLog("ClarifyHostTrace begin uptime=%.9f pid=%d generation=%llu", ProcessInfo.processInfo.systemUptime, ProcessInfo.processInfo.processIdentifier, generation)');
  replaceOnce('      let clock = ContinuousClock(), deadline = clock.now.advanced(by: .milliseconds(400))',
    '      let clock = ContinuousClock(), deadline = clock.now.advanced(by: .milliseconds(400))\n      NSLog("ClarifyHostTrace deadline-created uptime=%.9f pid=%d generation=%llu", ProcessInfo.processInfo.systemUptime, ProcessInfo.processInfo.processIdentifier, generation)');
  replaceOnce('    let request = ActivationRequest(sourceBundleID: source)',
    '    NSLog("ClarifyHostTrace resolved uptime=%.9f pid=%d source=%@", ProcessInfo.processInfo.systemUptime, ProcessInfo.processInfo.processIdentifier, source ?? "unknown")\n    let request = ActivationRequest(sourceBundleID: source)');
} else if (path.basename(source) === 'KBHostArbiterHook.m') {
  replaceOnce('#import <stdlib.h>', '#import <stdlib.h>\n#import <unistd.h>\n#define HT_LOG(format, ...) NSLog(@"ClarifyHostTrace uptime=%.9f pid=%d main=%d " format, NSProcessInfo.processInfo.systemUptime, getpid(), NSThread.isMainThread, ##__VA_ARGS__)');
  replaceOnce('    sCaptureGeneration += 1;\n    os_unfair_lock_unlock(&sHookLock);\n}',
    '    sCaptureGeneration += 1;\n    uint64_t traceGeneration = sCaptureGeneration;\n    os_unfair_lock_unlock(&sHookLock);\n    HT_LOG(@"capture generation=%llu accepted=%@", (unsigned long long)traceGeneration, accepted ?: @"unknown");\n}');
  replaceOnce('static void SwizzledKeyboardChanged(id self, SEL _cmd, id change, id completion) {\n    CaptureHost(change);',
    'static void SwizzledKeyboardChanged(id self, SEL _cmd, id change, id completion) {\n    HT_LOG(@"callback queue");\n    CaptureHost(change);');
  replaceOnce('static BOOL SwizzledHandledChange(id self, SEL _cmd, id change, BOOL snapshot, BOOL local) {\n    CaptureHost(change);',
    'static BOOL SwizzledHandledChange(id self, SEL _cmd, id change, BOOL snapshot, BOOL local) {\n    HT_LOG(@"callback handled");\n    CaptureHost(change);');
  replaceOnce('    os_unfair_lock_unlock(&sHookLock);\n}\n\n+ (void)activeArbiterCheck',
    '    BOOL traceQueue = sOriginalIMP != NULL, traceHandled = sOriginalHandledIMP != NULL, traceEnabled = sEnabledInstalled;\n    os_unfair_lock_unlock(&sHookLock);\n    HT_LOG(@"installed queue=%d handled=%d enabled=%d", traceQueue, traceHandled, traceEnabled);\n}\n\n+ (void)activeArbiterCheck');
  replaceOnce('    [self installHooks];\n    Class cls = NSClassFromString(kArbiterClientClassName);',
    '    HT_LOG(@"active-check begin");\n    [self installHooks];\n    Class cls = NSClassFromString(kArbiterClientClassName);');
  replaceOnce('      pingMsg(client, ping);', '      HT_LOG(@"ping begin");\n      pingMsg(client, ping);\n      HT_LOG(@"ping returned");');
  replaceOnce('    NSString *bid = fresh ? [sLastCapturedBundleId copy] : nil;\n    os_unfair_lock_unlock(&sHookLock);\n    return bid;',
    '    NSString *bid = fresh ? [sLastCapturedBundleId copy] : nil;\n    uint64_t traceCurrent = sCaptureGeneration, traceInvalidation = sInvalidationGeneration;\n    os_unfair_lock_unlock(&sHookLock);\n    HT_LOG(@"query after=%llu current=%llu invalidation=%llu fresh=%d result=%@", (unsigned long long)generation, (unsigned long long)traceCurrent, (unsigned long long)traceInvalidation, fresh, bid ?: @"unknown");\n    return bid;');
  replaceOnce('    sInvalidationGeneration = sCaptureGeneration;\n    os_unfair_lock_unlock(&sHookLock);',
    '    sInvalidationGeneration = sCaptureGeneration;\n    uint64_t traceGeneration = sCaptureGeneration;\n    os_unfair_lock_unlock(&sHookLock);\n    HT_LOG(@"invalidate generation=%llu", (unsigned long long)traceGeneration);');
} else throw new Error('Unsupported host trace source.');
fs.writeFileSync(output, text);

