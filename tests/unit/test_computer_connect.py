"""Desktop and mobile use one nonsecret relay deployment identity."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from shared.computer_connect import relay_configuration


class ComputerConnectConfigurationTests(unittest.TestCase):
    def test_unconfigured_build_does_not_select_a_public_service(self):
        self.assertEqual(relay_configuration(), {"relay_host": None, "relay_port": 443})

    def test_custom_build_retains_exact_host_and_port(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "computer_connect.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "relay_host": "relay.example.com",
                        "relay_port": 8443,
                    }
                )
            )
            self.assertEqual(
                relay_configuration(path),
                {"relay_host": "relay.example.com", "relay_port": 8443},
            )

    def test_invalid_or_missing_build_inputs_fail_without_disclosing_input(self):
        valid = {"schema_version": 1, "relay_host": None, "relay_port": 443}
        invalid = [
            {},
            {**valid, "schema_version": True},
            {**valid, "extra": "not-an-accepted-setting"},
            {**valid, "relay_port": True},
            {**valid, "relay_port": 0},
            {**valid, "relay_host": "https://private.example.com/secret"},
            {**valid, "relay_host": "relay.local"},
            {**valid, "relay_host": "relay.123"},
        ]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "computer_connect.json"
            for value in invalid:
                path.write_text(json.dumps(value))
                with (
                    self.subTest(value=value),
                    self.assertRaisesRegex(
                        ValueError, "^Invalid computer relay build configuration$"
                    ),
                ):
                    relay_configuration(path)
            path.unlink()
            with self.assertRaisesRegex(
                ValueError, "^Invalid computer relay build configuration$"
            ):
                relay_configuration(path)
