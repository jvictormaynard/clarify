import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


class SecretStoreContractTests(unittest.TestCase):
    def test_secret_store_cli_reports_only_safe_metadata(self):
        import app

        output = StringIO()
        with redirect_stdout(output):
            result = app._run_cli(["secret-store-self-test"])

        self.assertEqual(result, 0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["providers"], ["gemini", "openai", "groq"])
        self.assertFalse(payload["config_contains_provider_keys"])
        self.assertTrue(payload["restart_read"])
        self.assertTrue(payload["provider_connections_ready"])
        self.assertTrue(payload["delete_verified"])
        self.assertNotIn("clarify-self-test", output.getvalue())

    def test_secret_store_cli_can_write_result_file(self):
        import app

        with tempfile.TemporaryDirectory() as directory:
            result_file = Path(directory) / "result.json"
            output = StringIO()
            with redirect_stdout(output):
                result = app._run_cli(
                    [
                        "secret-store-self-test",
                        "--result-file",
                        str(result_file),
                    ]
                )

            self.assertEqual(result, 0)
            self.assertEqual(output.getvalue(), "")
            payload = json.loads(result_file.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["config_contains_provider_keys"])
            self.assertTrue(payload["restart_read"])
            self.assertTrue(payload["provider_connections_ready"])
            self.assertTrue(payload["delete_verified"])
            self.assertNotIn(
                "clarify-self-test", result_file.read_text(encoding="utf-8")
            )

    def test_secret_store_cli_succeeds_without_stdout(self):
        import app

        original_stdout = app.sys.stdout
        try:
            app.sys.stdout = None
            result = app._run_cli(["secret-store-self-test"])
        finally:
            app.sys.stdout = original_stdout

        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
