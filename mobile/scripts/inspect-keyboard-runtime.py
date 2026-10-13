"""Read simulator UIKit geometry instructions in an isolated empty process.

Diagnostic only. No app profiles, keys, recording, or product changes.
"""

import json
import os
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
        "-[_UIRemoteInputViewController intrinsicContentSizeForServiceSize:]",
        "-[_UIRemoteInputViewController viewDidInvalidateIntrinsicContentSize]",
        "-[_UISizeTrackingView updateIntrinsicContentSize:]",
        "-[_UISizeTrackingView _sizeForRemoteViewService]",
        "-[UICompatibilityInputViewController generateCompatibleSizeConstraintsIfNecessary]",
        "-[UICompatibilityInputViewController rebuildChildConstraints]",
        "-[UIInputViewController _systemLayoutSizeFittingSize:withHorizontalFittingPriority:verticalFittingPriority:]",
        "-[_UIViewServiceViewControllerOperator systemLayoutFittingSizeDidChangeForChildViewController:]",
        "-[_UIViewServiceViewControllerOperator __setContentSize:boundingPath:withFence:]",
    ]
    commands = ["settings set target.process.stop-on-sharedlibrary-events false"]
    commands += [f'disassemble --name "{method}"' for method in methods]
    commands += ["process detach", "quit"]
    script = root / "inspect.lldb"
    script.write_text("\n".join(commands) + "\n")
    print("Reading UIKit functions", flush=True)
    result = subprocess.run(
        ["lldb", "--batch", "-p", pid, "-s", str(script)],
        text=True,
        capture_output=True,
        timeout=120,
    )
    (results / "geometry-disassembly.txt").write_text(result.stdout + result.stderr)
    print("Debugger exit", result.returncode, flush=True)
    if result.returncode:
        print((result.stdout + result.stderr)[-2000:])
        raise SystemExit(result.returncode)
