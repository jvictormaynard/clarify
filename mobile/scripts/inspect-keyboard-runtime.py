"""Read the simulator keyboard background contract in an empty process.

Diagnostic only. No app profiles, keys, recording, or product changes.
"""

import json
from pathlib import Path
import plistlib
import subprocess
import tempfile


def run(*args, **kwargs):
    return subprocess.run(
        args, check=True, text=True, capture_output=True, timeout=240, **kwargs
    ).stdout


results = Path(__file__).resolve().parents[1] / "test-results/runtime-inspect"
results.mkdir(parents=True, exist_ok=True)
devices = json.loads(run("xcrun", "simctl", "list", "devices", "available", "--json"))[
    "devices"
]
device = next(
    d
    for runtime, items in devices.items()
    if "iOS-26-5" in runtime
    for d in items
    if d["name"].startswith("iPhone")
)
print("Booting", device["name"], flush=True)
run("xcrun", "simctl", "bootstatus", device["udid"], "-b")
sdk = run("xcrun", "--sdk", "iphonesimulator", "--show-sdk-path").strip()
with tempfile.TemporaryDirectory(prefix="clarify-runtime-inspect-") as folder:
    root = Path(folder)
    app = root / "RuntimeProbe.app"
    app.mkdir()
    source = root / "RuntimeProbe.swift"
    source.write_text("""import UIKit
@main final class RuntimeProbe: UIResponder, UIApplicationDelegate {
 var window: UIWindow?
 func application(_ application: UIApplication, didFinishLaunchingWithOptions options: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
  let window = UIWindow(frame: UIScreen.main.bounds)
  window.rootViewController = UIViewController()
  window.makeKeyAndVisible(); self.window = window; return true
 }
}
""")
    with (app / "Info.plist").open("wb") as file:
        plistlib.dump(
            {
                "CFBundleIdentifier": "com.clarify.geometry.inspect",
                "CFBundleExecutable": "RuntimeProbe",
                "CFBundleName": "RuntimeProbe",
                "CFBundlePackageType": "APPL",
                "CFBundleVersion": "1",
                "CFBundleShortVersionString": "1.0",
                "UILaunchScreen": {},
                "UIDeviceFamily": [1],
            },
            file,
        )
    print("Compiling empty diagnostic host", flush=True)
    run(
        "xcrun",
        "--sdk",
        "iphonesimulator",
        "swiftc",
        "-parse-as-library",
        "-sdk",
        sdk,
        "-target",
        "arm64-apple-ios16.4-simulator",
        str(source),
        "-o",
        str(app / "RuntimeProbe"),
    )
    run("xcrun", "simctl", "install", device["udid"], str(app))
    launched = run(
        "xcrun", "simctl", "launch", device["udid"], "com.clarify.geometry.inspect"
    )
    pid = launched.rsplit(":", 1)[1].strip()
    methods = [
        "-[UIInputViewSet isInputViewPlaceholder]",
        "-[UIInputViewController _isPlaceholder]",
        "-[UICompatibilityInputViewController loadView]",
        "-[UICompatibilityInputViewController setInputController:]",
    ]
    commands = [
        "settings set target.process.stop-on-sharedlibrary-events false",
        "settings set interpreter.stop-command-source-on-error false",
    ]
    # An unavailable private symbol is diagnostic data. Keep reading the other
    # contracts instead of letting LLDB abort the command-source file.
    debugger_commands = [
        'image lookup -rn "_isPlaceholder"',
        *[f'disassemble --name "{method}"' for method in methods],
        "expression -l objc++ -- @import Foundation;",
        "expression -l objc++ -- @import ObjectiveC;",
        r"""expression -l objc++ -O -- ({
            NSMutableString *clarifyBgOutput = [NSMutableString string];
            const char *clarifyBgClassNames[] = { "UIInputViewController", "UICompatibilityInputViewController",
                "_UIRemoteInputViewController", "_UIRemoteViewController" };
            SEL clarifyBgSelector = sel_registerName("_isPlaceholder");
            for (unsigned int clarifyBgClassIndex = 0; clarifyBgClassIndex < 4; clarifyBgClassIndex++) {
                Class clarifyBgClass = objc_getClass(clarifyBgClassNames[clarifyBgClassIndex]);
                Method clarifyBgEffective = clarifyBgClass ? class_getInstanceMethod(clarifyBgClass, clarifyBgSelector) : NULL;
                Class clarifyBgDeclaring = Nil;
                for (Class clarifyBgCursor = clarifyBgClass; clarifyBgCursor && !clarifyBgDeclaring; clarifyBgCursor = class_getSuperclass(clarifyBgCursor)) {
                    unsigned int clarifyBgCount = 0;
                    Method *clarifyBgMethods = class_copyMethodList(clarifyBgCursor, &clarifyBgCount);
                    for (unsigned int clarifyBgMethodIndex = 0; clarifyBgMethodIndex < clarifyBgCount; clarifyBgMethodIndex++) {
                        if (method_getName(clarifyBgMethods[clarifyBgMethodIndex]) == clarifyBgSelector) { clarifyBgDeclaring = clarifyBgCursor; break; }
                    }
                    free(clarifyBgMethods);
                }
                Class clarifyBgSuperclass = clarifyBgClass ? class_getSuperclass(clarifyBgClass) : Nil;
                [clarifyBgOutput appendFormat:@"class=%s super=%s declaringOwner=%s localOverride=%d types=%s IMP=%p\n",
                    clarifyBgClassNames[clarifyBgClassIndex], clarifyBgSuperclass ? class_getName(clarifyBgSuperclass) : "missing",
                    clarifyBgDeclaring ? class_getName(clarifyBgDeclaring) : "missing", clarifyBgDeclaring != Nil && clarifyBgDeclaring == clarifyBgClass,
                    clarifyBgEffective ? method_getTypeEncoding(clarifyBgEffective) : "missing",
                    clarifyBgEffective ? (void *)method_getImplementation(clarifyBgEffective) : NULL];
            }
            clarifyBgOutput;
        })""",
    ]
    inspect = "import lldb\ninterpreter = lldb.debugger.GetCommandInterpreter()\n"
    debugger_commands = [command.replace("\n", " ") for command in debugger_commands]
    inspect += f"for command in {debugger_commands!r}:\n"
    inspect += "    result = lldb.SBCommandReturnObject()\n"
    inspect += "    interpreter.HandleCommand(command, result)\n"
    inspect += "    print(command, flush=True)\n"
    inspect += "    print(result.GetOutput() or '', flush=True)\n"
    inspect += "    print(result.GetError() or '', flush=True)\n"
    commands += [f"script exec({inspect!r})"]
    commands += ["process detach", "quit"]
    script = root / "inspect.lldb"
    script.write_text("\n".join(commands) + "\n")
    print("Reading UIKit functions", flush=True)
    with (results / "geometry-disassembly.txt").open("w") as debugger_output:
        result = subprocess.run(
            ["lldb", "--batch", "-p", pid, "-s", str(script)],
            text=True,
            stdout=debugger_output,
            stderr=subprocess.STDOUT,
            timeout=180,
        )
    print("Debugger exit", result.returncode, flush=True)
    if result.returncode:
        print((results / "geometry-disassembly.txt").read_text()[-2000:])
        raise SystemExit(result.returncode)
