"""Prepare an instrumented, non-publication copy of one frozen iOS source."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

SOURCE = "678772aadda5d5eec78bd8f2b818635a7657ba90"
TREE = "269a7d233249a23e556af8cf012b47f5dd646b33"
SWIFT = "mobile/native/keyboard/KeyboardViewController.swift"
ARBITER = "mobile/native/keyboard/KBHostArbiterHook.m"
HEIGHT = "mobile/native/keyboard/KeyboardHeightSync.m"
COLLECTOR = "mobile/scripts/test-keyboard-extension.cjs"
C_LOGGER = """#import <os/log.h>
#import <mach/mach_time.h>
static void ClarifyStartupProbe(const char *marker) {
    os_log_error(OS_LOG_DEFAULT,
        "ClarifyStartup marker=%{public}s clock=mach_continuous ticks=%{public}llu",
        marker, (unsigned long long)mach_continuous_time());
}

"""


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def sha(data):
    return hashlib.sha256(data).hexdigest()


def swift_log(marker):
    return (
        'NSLog("ClarifyStartup marker='
        + marker
        + ' clock=dispatch_uptime_ns ticks=%llu main=%d", '
        + "DispatchTime.now().uptimeNanoseconds, Int32(Thread.isMainThread ? 1 : 0))"
    )


def instrument(name, original):
    text = original.decode("utf-8")
    undo = []

    def change(old, new):
        nonlocal text
        if text.count(old) != 1:
            raise ValueError(f"Diagnostic anchor not unique: {name}: {old[:65]!r}")
        text = text.replace(old, new, 1)
        undo.append((new, old))

    if name == SWIFT:
        for method in (
            "loadView()",
            "viewDidLoad()",
            "viewWillAppear(_ animated: Bool)",
            "viewDidAppear(_ animated: Bool)",
            "viewDidDisappear(_ animated: Bool)",
        ):
            header = "  override func " + method + " {\n"
            label = "controller." + method.split("(", 1)[0]
            change(
                header,
                header
                + "    "
                + swift_log(label + ".enter")
                + "\n"
                + "    defer { "
                + swift_log(label + ".exit")
                + " }\n",
            )
        change(
            "    super.viewDidLoad()\n",
            "    super.viewDidLoad()\n    "
            + swift_log("controller.viewDidLoad.super-returned")
            + "\n",
        )
        change(
            "  deinit { timer?.invalidate() }",
            "  deinit { " + swift_log("controller.deinit") + "; timer?.invalidate() }",
        )
    elif name == ARBITER:
        change(
            "+ (void)load {\n    if (@available(iOS 26.4, *)) {\n"
            "        [self installHooks];\n    }\n}",
            '+ (void)load {\n    ClarifyStartupProbe("arbiter.load.enter");\n'
            "    if (@available(iOS 26.4, *)) {\n        [self installHooks];\n    }\n"
            '    ClarifyStartupProbe("arbiter.load.exit");\n}',
        )
        start = text.index("+ (void)installHooks {\n")
        end = text.index("\n+ (void)activeArbiterCheck", start)
        block = text[start:end]
        new = (
            block.replace(
                "+ (void)installHooks {\n",
                '+ (void)installHooks {\n    ClarifyStartupProbe("arbiter.install.enter");\n',
                1,
            )
            .replace(
                "    os_unfair_lock_lock(&sHookLock);\n",
                "    os_unfair_lock_lock(&sHookLock);\n"
                '    ClarifyStartupProbe("arbiter.install.lock-acquired");\n',
                1,
            )
            .replace(
                "    os_unfair_lock_unlock(&sHookLock);\n",
                "    os_unfair_lock_unlock(&sHookLock);\n"
                '    ClarifyStartupProbe("arbiter.install.exit");\n',
                1,
            )
        )
        change(block, new)
    elif name == HEIGHT:
        change(
            "+ (void)load {\n    Class type",
            '+ (void)load {\n    ClarifyStartupProbe("height.load.enter");\n    Class type',
        )
        change(
            "        keyboardHeightOriginalHostReady = (void *)method_setImplementation(method, (IMP)heightHostReady);\n}",
            "        keyboardHeightOriginalHostReady = (void *)method_setImplementation(method, (IMP)heightHostReady);\n"
            '    ClarifyStartupProbe("height.load.exit");\n}',
        )
        change(
            "    keyboardHeightOriginalHostReady(object, command);\n",
            '    ClarifyStartupProbe("height.host-ready.original.enter");\n'
            "    keyboardHeightOriginalHostReady(object, command);\n"
            '    ClarifyStartupProbe("height.host-ready.original.exit");\n',
        )
        change(
            "    state.owner = object;\n",
            "    state.owner = object;\n"
            '    ClarifyStartupProbe("height.owner-associated");\n',
        )
        change(
            "            ((void (*)(id, SEL, CGSize, id))objc_msgSend)(proxy, update, size, fence);\n",
            '            ClarifyStartupProbe("height.publish.enter");\n'
            "            ((void (*)(id, SEL, CGSize, id))objc_msgSend)(proxy, update, size, fence);\n"
            '            ClarifyStartupProbe("height.publish.exit");\n',
        )
    elif name == COLLECTOR:
        change("let exitCode = 1;\n", "let exitCode = 1;\nlet startupLogCollection;\n")
        change(
            '\'process IN {"ClarifyKeyboard", "ActivationContainer", "KeyboardHost"}\'',
            '\'eventMessage CONTAINS "com.clarify.fixture.container.keyboard" OR '
            'eventMessage CONTAINS "ClarifyStartup" OR '
            'process IN {"ClarifyKeyboard", "ActivationContainer", "KeyboardHost"}\'',
        )
        change(
            "'show', '--style', 'compact',",
            "'show', '--info', '--debug', '--style', 'compact',",
        )
        change("maxBuffer: 16 * 1024 * 1024", "maxBuffer: 64 * 1024 * 1024")
        log_write = (
            "  fs.writeFileSync(path.join(results, 'extension-log.txt'), "
            "(logs.stdout ?? '') + (logs.stderr ?? ''));\n"
        )
        change(
            log_write,
            log_write + "  startupLogCollection = {\n"
            "    status: logs.status ?? null, signal: logs.signal ?? null,\n"
            "    errorCode: logs.error?.code ?? null,\n"
            "    stdoutBytes: Buffer.byteLength(logs.stdout ?? ''),\n"
            "    stderrBytes: Buffer.byteLength(logs.stderr ?? ''),\n"
            "    complete: logs.status === 0 && !logs.error && !logs.signal,\n"
            "  };\n"
            "  fs.writeFileSync(path.join(results, 'log-collection.json'), JSON.stringify(startupLogCollection, null, 2));\n",
        )
        change(
            "['KeyboardViewController.swift', 'App.plist',",
            "['SharedState.swift', 'KeyboardViewController.swift', 'App.plist',",
        )
        change(
            "{ runtime, device: device.name, strictOpeningHeight, keyboardHeightDiagnostics, exitCode }",
            "{ runtime, device: device.name, strictOpeningHeight, keyboardHeightDiagnostics, "
            "startupProbeOnly: true, publicationAllowed: false, exitCode, "
            "logCollection: startupLogCollection, diagnosticIncomplete: !startupLogCollection.complete }",
        )
        change(
            "process.exitCode = exitCode;",
            "process.exitCode = exitCode !== 0 ? exitCode : (startupLogCollection?.complete === true ? 0 : 2);",
        )
        change(
            "let startupLogCollection;\n",
            "let startupLogCollection;\nlet startupSystemLogCollection;\n",
        )
        change(
            "  fs.writeFileSync(path.join(results, 'log-collection.json'), JSON.stringify(startupLogCollection, null, 2));\n",
            "  fs.writeFileSync(path.join(results, 'log-collection.json'), JSON.stringify(startupLogCollection, null, 2));\n  const systemOutputPath = path.join(results, 'simulator-system.log');\n  const systemErrorPath = path.join(results, 'simulator-system-stderr.log');\n  let systemOutput;\n  let systemError;\n  let systemLogs = {};\n  let systemErrorCode = null;\n  const rememberSystemError = error => {\n    systemErrorCode ??= typeof error?.code === 'string' ? error.code : 'SYSTEM_LOG_IO_ERROR';\n  };\n  try {\n    systemOutput = fs.openSync(systemOutputPath, 'wx');\n    systemError = fs.openSync(systemErrorPath, 'wx');\n    systemLogs = spawnSync('xcrun', ['simctl', 'spawn', device.udid, 'log', 'show', '--info', '--debug', '--style', 'compact', '--last', '15m'], { stdio: ['ignore', systemOutput, systemError] });\n  } catch (error) {\n    rememberSystemError(error);\n  } finally {\n    for (const descriptor of [systemError, systemOutput]) {\n      if (descriptor === undefined) continue;\n      try { fs.closeSync(descriptor); }\n      catch (error) { rememberSystemError(error); }\n    }\n  }\n  const systemFileSize = target => {\n    try { return fs.statSync(target).size; }\n    catch (error) { rememberSystemError(error); return null; }\n  };\n  const systemOutputBytes = systemFileSize(systemOutputPath);\n  const systemErrorBytes = systemFileSize(systemErrorPath);\n  startupSystemLogCollection = {\n    status: systemLogs.status ?? null, signal: systemLogs.signal ?? null,\n    errorCode: systemErrorCode ?? systemLogs.error?.code ?? null,\n    stdoutBytes: systemOutputBytes, stderrBytes: systemErrorBytes,\n    complete: systemLogs.status === 0 && !systemLogs.error && !systemLogs.signal && systemErrorCode === null,\n    scope: 'all simulator processes, last 15m', streamedToFiles: true, metadataWritten: true,\n  };\n  try {\n    fs.writeFileSync(path.join(results, 'system-log-collection.json'), JSON.stringify(startupSystemLogCollection, null, 2));\n  } catch (error) {\n    rememberSystemError(error);\n    startupSystemLogCollection.complete = false;\n    startupSystemLogCollection.errorCode = systemErrorCode;\n    startupSystemLogCollection.metadataWritten = false;\n    console.warn('Full simulator log metadata unavailable; diagnosis incomplete.');\n  }\n",
        )
        change(
            "logCollection: startupLogCollection, diagnosticIncomplete: !startupLogCollection.complete }",
            "logCollection: startupLogCollection, systemLogCollection: startupSystemLogCollection, diagnosticIncomplete: !startupLogCollection.complete || !startupSystemLogCollection.complete }",
        )
        change(
            "process.exitCode = exitCode !== 0 ? exitCode : (startupLogCollection?.complete === true ? 0 : 2);",
            "process.exitCode = exitCode !== 0 ? exitCode : (startupLogCollection?.complete === true && startupSystemLogCollection?.complete === true ? 0 : 2);",
        )
    else:
        raise ValueError("Unexpected diagnostic target")
    if name in (ARBITER, HEIGHT):
        text = C_LOGGER + text
    restored = text.removeprefix(C_LOGGER) if name in (ARBITER, HEIGHT) else text
    for new, old in reversed(undo):
        if restored.count(new) != 1:
            raise ValueError("Cannot prove diagnostic reversibility")
        restored = restored.replace(new, old, 1)
    if restored.encode("utf-8") != original:
        raise ValueError("Diagnostic changed more than its reversible observations")
    return text.encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--probe", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    if git(source, "rev-parse", "HEAD").decode().strip() != SOURCE:
        raise ValueError("Diagnostic source must be the frozen build40 commit")
    if git(source, "rev-parse", "HEAD^{tree}").decode().strip() != TREE:
        raise ValueError("Diagnostic source tree mismatch")
    if git(source, "status", "--porcelain", "--untracked-files=no").strip():
        raise ValueError("Baseline checkout has tracked modifications")
    changes = {}
    evidence = args.evidence.resolve()
    if evidence.exists():
        raise ValueError("Use a new evidence directory; do not overwrite results")
    for name in (SWIFT, ARBITER, HEIGHT, COLLECTOR):
        original = git(source, "show", SOURCE + ":" + name)
        changed = instrument(name, original)
        changes[name] = (original, changed)
    if not args.dry_run:
        if not args.probe or not os.environ.get("RUNNER_TEMP"):
            raise ValueError("Execution requires a new probe under RUNNER_TEMP")
        probe = args.probe.resolve()
        runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
        if (
            not probe.is_relative_to(runner_temp)
            or probe == runner_temp
            or probe.exists()
        ):
            raise ValueError("Probe must be a new child directory of RUNNER_TEMP")
        subprocess.run(
            [
                "git",
                "-C",
                str(source),
                "worktree",
                "add",
                "--detach",
                str(probe),
                SOURCE,
            ],
            check=True,
        )
        for name, (_, changed) in changes.items():
            (probe / name).write_bytes(changed)
        print("probe=" + str(probe))
    evidence.mkdir(parents=True)
    for name, (_, changed) in changes.items():
        target = evidence / "instrumented" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(changed)
    result = {
        "source": SOURCE,
        "sourceTree": TREE,
        "diagnosticOnly": True,
        "publicationAllowed": False,
        "baselineCheckoutModified": False,
        "sourceCommitOrTagModified": False,
        "probeInstrumented": True,
        "dryRun": args.dry_run,
        "question": "Which startup stage precedes service refusal and late host invalidation?",
        "limitations": "Logging can affect timing; a pass is not a causal repair or publication validation.",
        "reversible": True,
        "inputs": [
            {"path": name, "originalSha256": sha(original), "probeSha256": sha(changed)}
            for name, (original, changed) in changes.items()
        ],
        "unchangedTestSha256": sha(
            git(
                source,
                "show",
                SOURCE + ":mobile/native/tests/KeyboardExtensionTests.swift",
            )
        ),
        "run": os.environ.get("GITHUB_RUN_ID"),
        "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
    }
    (evidence / "probe-manifest.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
