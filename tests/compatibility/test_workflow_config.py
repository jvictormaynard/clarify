"""Focused contracts for workflow-scoped provider configuration (#51)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from repositories import (
    LocalConfigRepository,
    WorkflowScope,
)
from secret_store import MemorySecretStore


class WorkflowConfigurationTests(unittest.TestCase):
    def test_legacy_app_save_refreshes_nested_routes_for_later_saves(self):
        import app

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            repository = LocalConfigRepository(path, secret_store=MemorySecretStore())
            storage = SimpleNamespace(config=repository)
            initial = repository.load().to_legacy_mapping()
            with patch.object(app, "APP_CONFIG", initial):
                app.APP_CONFIG.update(
                    {
                        "refinement_provider": "groq",
                        "refinement_model": "llama-3.3-70b-versatile",
                    }
                )
                app._save_app_config(storage)
                self.assertEqual(
                    app.APP_CONFIG["workflows"]["refinement"]["provider_id"],
                    "groq",
                )
                app.APP_CONFIG["ui_language"] = "pt"
                app._save_app_config(storage)

            loaded = repository.load()
            self.assertEqual(
                loaded.workflow(WorkflowScope.REWRITE).provider_id,
                "groq",
            )


if __name__ == "__main__":
    unittest.main()
