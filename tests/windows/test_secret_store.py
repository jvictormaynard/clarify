import os
import tempfile
import unittest
from pathlib import Path

from secret_store import (
    DpapiSecretStore,
    SecretStoreUnavailableError,
    create_secret_store,
)


class SecretStoreContractTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "requires the real Windows DPAPI")
    def test_real_windows_dpapi_round_trip_all_providers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secrets.dpapi.json"
            first = DpapiSecretStore(path)
            expected = {
                provider: f"non-production-{provider}-credential"
                for provider in (
                    "gemini",
                    "openai",
                    "groq",
                    "chatgpt",
                    "clarify_computer",
                )
            }
            for provider, value in expected.items():
                first.set(provider, value)

            second = DpapiSecretStore(path)
            self.assertEqual(
                {provider: second.get(provider) for provider in expected},
                expected,
            )
            for provider in expected:
                second.delete(provider)

            self.assertFalse(path.exists())

    def test_windows_factory_is_lazy_when_dpapi_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            store = create_secret_store(directory, system="Windows")

            self.assertIsInstance(store, DpapiSecretStore)
            self.assertIsNone(store.get("openai"))
            if os.name == "nt":
                store.set("openai", "test-openai-credential")
                self.assertEqual(store.get("openai"), "test-openai-credential")
            else:
                with self.assertRaises(SecretStoreUnavailableError):
                    store.set("openai", "test-openai-credential")


if __name__ == "__main__":
    unittest.main()
