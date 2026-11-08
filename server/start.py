"""Migrate under one PostgreSQL lock, then replace this process with Gunicorn."""

import os
from pathlib import Path
import sys

sys.path[:0] = [
    str(Path(__file__).resolve().parent),
    str(Path(__file__).resolve().parents[1]),
]
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cloud.settings")
# exec replaces Python's sys.path; Gunicorn must still find the shared modules.
os.environ["PYTHONPATH"] = os.pathsep.join(
    filter(
        None, [str(Path(__file__).resolve().parents[1]), os.environ.get("PYTHONPATH")]
    )
)
import django  # noqa: E402 -- configure the settings module before initialization

django.setup()
from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402

with connection.cursor() as cursor:
    cursor.execute("SELECT pg_advisory_lock(384136731)")
    try:
        call_command("migrate", interactive=False, verbosity=0)
        call_command("createcachetable", verbosity=0)
    finally:
        cursor.execute("SELECT pg_advisory_unlock(384136731)")
connection.close()
os.chdir(Path(__file__).resolve().parent)
os.execvp(
    "gunicorn",
    ["gunicorn", "--config", "cloud/gunicorn.conf.py", "cloud.wsgi:application"],
)
