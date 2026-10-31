"""Own Linux browser descendants, including separate sessions and orphaned children.

Use only the Python standard library. A child subreaper retains descendants after
the CLI exits. Parent death requests cleanup; no process is addressed by a shell.
"""

import base64
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def descendants():
    parents = {}
    for path in Path("/proc").iterdir():
        if not path.name.isdecimal():
            continue
        try:
            stat = (path / "stat").read_bytes()
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        fields = stat[stat.rfind(b")") + 2 :].split()
        parents[int(path.name)] = (int(fields[1]), fields[19])
    owned = {os.getpid()}
    while True:
        found = {pid for pid, (parent, _) in parents.items() if parent in owned}
        if found <= owned:
            return {pid: parents[pid][1] for pid in owned if pid != os.getpid()}
        owned.update(found)


def kill_owned():
    deadline = time.monotonic() + 10
    while True:
        children = descendants()
        for pid, started in children.items():
            try:
                descriptor = os.pidfd_open(pid)
            except ProcessLookupError:
                continue
            try:
                # Bind the signal to this process identity, including across PID reuse.
                stat = Path(f"/proc/{pid}/stat").read_bytes()
                if stat[stat.rfind(b")") + 2 :].split()[19] == started:
                    signal.pidfd_send_signal(descriptor, signal.SIGKILL)
            except (FileNotFoundError, ProcessLookupError):
                pass
            finally:
                os.close(descriptor)
        try:
            while os.waitpid(-1, os.WNOHANG)[0]:
                pass
        except ChildProcessError:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError("Owned browser descendants did not stop")
        time.sleep(0.02)


def main():
    if sys.platform != "linux":
        raise RuntimeError("Browser process supervision requires Linux or Windows")
    request = json.loads(base64.b64decode(sys.argv[1], validate=True))
    cancelled = False

    def stop(_signal, _frame):
        nonlocal cancelled
        cancelled = True

    for kind in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(kind, stop)
    libc = ctypes.CDLL(None, use_errno=True)
    # PR_SET_CHILD_SUBREAPER and PR_SET_PDEATHSIG must precede child creation.
    for option, value in ((36, 1), (1, signal.SIGTERM)):
        if libc.prctl(option, value, 0, 0, 0) != 0:
            raise OSError(
                ctypes.get_errno(), "Cannot establish browser process ownership"
            )
    if os.getppid() != request["parent"]:
        return 1
    process = None
    try:
        process = subprocess.Popen(
            [request["file"], *request["arguments"]], start_new_session=True
        )
        while process.poll() is None and not cancelled:
            time.sleep(0.02)
        # Save the CLI result before reaping any adopted descendants.
        code = process.returncode if process.returncode is not None else 1
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        kill_owned()
    return code if code >= 0 else 128 - code


if __name__ == "__main__":
    raise SystemExit(main())
