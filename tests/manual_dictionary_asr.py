"""Opt-in smoke against verified local Whisper, using a synthetic WAV only.

Usage: python tests/manual_dictionary_asr.py synthetic.wav
Does not change user settings or use the application's recorded-process slot.
"""

import queue
import secrets
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from local_asr import LocalASRInstaller, LocalASRSidecarManager


def main():
    installer = LocalASRInstaller()
    assert installer.status()["state"] == "installed", "Verified local model required"
    manager = LocalASRSidecarManager(installer, request_timeout=90)
    manager._port = manager._reserve_port()
    manager._request_path = "/" + secrets.token_urlsafe(24)
    command = [
        str(installer.executable_path),
        "--model",
        str(installer.model_path),
        "--host",
        "127.0.0.1",
        "--port",
        str(manager._port),
        "--request-path",
        manager._request_path,
        "--threads",
        "4",
        "--no-gpu",
        "--no-timestamps",
        "--max-context",
        "0",
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Whisper exited before health check")
            try:
                if manager._session.get(manager.base_url + "/health", timeout=1).ok:
                    break
            except Exception:
                pass
            time.sleep(0.2)
        else:
            raise TimeoutError("Whisper startup timed out")
        audio = Path(sys.argv[1]).read_bytes()
        for prompt in ("Railway, pill, Lana, Eva Desktop", ""):
            result = queue.Queue()
            manager._post_inference("synthetic.wav", audio, "en", result, prompt)
            text, error = result.get_nowait()
            if error:
                raise error
            assert text and text.strip()
            print(
                f"PASS: local inference {'with vocabulary' if prompt else 'after clearing vocabulary'}: {text}",
                flush=True,
            )
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        manager._session.close()


if __name__ == "__main__":
    main()
