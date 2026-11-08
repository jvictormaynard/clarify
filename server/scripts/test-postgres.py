"""Run server tests on an isolated disposable PostgreSQL, never a real profile."""

import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
binary = Path(os.environ.get("PG_BIN", "/usr/lib/postgresql/16/bin"))
with tempfile.TemporaryDirectory(prefix="clarify-pg-test-") as temporary:
    data = Path(temporary) / "database"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    subprocess.run(
        [
            str(binary / "initdb"),
            "-D",
            str(data),
            "--auth=trust",
            "--no-locale",
            "--encoding=UTF8",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    subprocess.run(
        [
            str(binary / "pg_ctl"),
            "-D",
            str(data),
            "-l",
            str(Path(temporary) / "pg.log"),
            "-o",
            f"-h 127.0.0.1 -p {port} -k {temporary}",
            "-w",
            "start",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    try:
        env = {
            **os.environ,
            "CLARIFY_DEVELOPMENT": "1",
            "CLARIFY_SIGNUP_ENABLED": "1",
            "DATABASE_URL": f"postgresql://{os.environ['USER']}@127.0.0.1:{port}/postgres",
        }
        status = subprocess.run(
            [
                sys.executable,
                str(root / "server/manage.py"),
                "test",
                "cloud.service.tests",
                "--noinput",
            ],
            cwd=root,
            env=env,
        ).returncode
    finally:
        subprocess.run(
            [str(binary / "pg_ctl"), "-D", str(data), "-m", "immediate", "-w", "stop"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    sys.exit(status)
