"""Run the shared validation CLI from any supported Python environment."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ci.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
