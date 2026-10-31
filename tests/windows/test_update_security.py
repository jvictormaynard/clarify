import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


from update_security import (
    SignatureError,
    UpdatePolicy,
    _AUTHENTICODE_TIMESTAMP_INSPECTOR,
    verify_authenticode,
)


POLICY = UpdatePolicy(
    repository="jvictormaynard/clarify",
    channel="stable",
    manifest_asset="Clarify-release-manifest.cab",
    installer_asset="Clarify-windows-x64.msi",
    publisher_common_name="Joao Victor Maynard Mota",
    require_rfc3161_timestamp=True,
    maximum_download_bytes=1024 * 1024,
)


def manifest_bytes(version="0.2.0", **asset_overrides):
    asset = {
        "name": POLICY.installer_asset,
        "url": (
            "https://github.com/jvictormaynard/clarify/"
            f"releases/download/v{version}/{POLICY.installer_asset}"
        ),
        "sha256": "a" * 64,
        "size": 3,
        "publisher_common_name": POLICY.publisher_common_name,
    }
    asset.update(asset_overrides)
    return json.dumps(
        {
            "schema_version": 1,
            "version": version,
            "release_tag": f"v{version}",
            "channel": "stable",
            "asset": asset,
        },
        separators=(",", ":"),
    ).encode()


class SignatureValidationTests(unittest.TestCase):
    def _verify(self, artifact, payload, *, signtool_result=None):
        powershell_result = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )
        if signtool_result is None:
            signtool_result = SimpleNamespace(
                returncode=0,
                # SignTool stdout is deliberately not parsed. Its documented
                # exit status is the only accepted chain-verification signal.
                stdout="unstructured SignTool output",
                stderr="",
            )
        runner = Mock(side_effect=[powershell_result, signtool_result])
        identity = verify_authenticode(
            artifact,
            POLICY.publisher_common_name,
            require_timestamp=POLICY.require_rfc3161_timestamp,
            runner=runner,
            powershell="powershell.exe",
            signtool="signtool.exe",
        )
        powershell_script = runner.call_args_list[0].args[0][-1]
        for field in (
            "CryptQueryObject",
            "CryptMsgGetParam",
            "CmsgSignerUnauthAttrParam",
            "Marshal.SizeOf",
            "IntPtr.Add",
            "CertQueryContentPkcs7SignedEmbed",
            "CertQueryFormatBinary",
            "1.2.840.113549.1.9.16.2.14",
            "1.2.840.113549.1.9.6",
            "TimeStamperCertificate",
            "TimestampStatus",
            "TimestampProtocol",
            "TimestampCommonName",
            "TimestampThumbprint",
        ):
            self.assertIn(field, powershell_script)
        self.assertNotIn("Index  Algorithm  Timestamp", powershell_script)
        self.assertNotIn("/v", powershell_script)
        self.assertNotIn("Marshal.ReadIntPtr", powershell_script)
        signtool_command = runner.call_args_list[1].args[0]
        self.assertEqual(
            signtool_command,
            [
                "signtool.exe",
                "verify",
                "/pa",
                "/all",
                "/tw",
                str(artifact.resolve()),
            ],
        )
        return identity

    def _valid_payload(self, **overrides):
        payload = {
            "Status": "Valid",
            "StatusMessage": "Signature verified.",
            "CommonName": POLICY.publisher_common_name,
            "Thumbprint": "AB" * 20,
            # The PowerShell side structurally identifies the RFC3161 OID;
            # SignTool separately validates the Windows/TSA chain.
            "TimestampStatus": "Valid",
            "TimestampProtocol": "RFC3161",
            "TimestampCommonName": "Trusted RFC3161 TSA",
            "TimestampThumbprint": "CD" * 20,
        }
        payload.update(overrides)
        return payload

    def test_accepts_valid_signature_publisher_and_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "artifact.msi"
            artifact.write_bytes(b"signed")
            identity = self._verify(artifact, self._valid_payload())
            self.assertEqual(identity.thumbprint, "AB" * 20)
            self.assertEqual(identity.timestamp_common_name, "Trusted RFC3161 TSA")
            self.assertEqual(identity.timestamp_thumbprint, "CD" * 20)

    def test_rejects_missing_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "artifact.msi"
            artifact.write_bytes(b"signed-without-timestamp")
            with self.assertRaises(SignatureError):
                self._verify(
                    artifact,
                    self._valid_payload(
                        TimestampStatus="Missing",
                        TimestampProtocol="Missing",
                        TimestampCommonName="",
                        TimestampThumbprint="",
                    ),
                )

    def test_rejects_invalid_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "artifact.msi"
            artifact.write_bytes(b"signed-with-invalid-timestamp")
            with self.assertRaises(SignatureError):
                self._verify(
                    artifact,
                    self._valid_payload(
                        TimestampStatus="Invalid",
                        TimestampProtocol="Invalid",
                    ),
                )

    def test_rejects_legacy_authenticode_countersignature(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "artifact.msi"
            artifact.write_bytes(b"signed-with-legacy-timestamp")
            with self.assertRaises(SignatureError):
                self._verify(
                    artifact,
                    self._valid_payload(
                        TimestampStatus="Invalid",
                        TimestampProtocol="Legacy",
                    ),
                )

    def test_rejects_malformed_rfc3161_attribute(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "artifact.msi"
            artifact.write_bytes(b"signed-with-malformed-rfc3161")
            with self.assertRaises(SignatureError):
                self._verify(
                    artifact,
                    self._valid_payload(
                        TimestampStatus="Invalid",
                        TimestampProtocol="Invalid",
                    ),
                )

    def test_rejects_untrusted_or_invalid_timestamp_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "artifact.msi"
            artifact.write_bytes(b"signed-with-untrusted-tsa")
            invalid_tsa = SimpleNamespace(
                returncode=1,
                stdout="",
                stderr=(
                    "SignTool Error: A certificate chain processed, but "
                    "terminated in an untrusted root."
                ),
            )
            with self.assertRaises(SignatureError):
                self._verify(
                    artifact, self._valid_payload(), signtool_result=invalid_tsa
                )

    def test_rejects_signtool_warning_even_with_valid_structural_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "artifact.msi"
            artifact.write_bytes(b"signed-with-timestamp-warning")
            warning = SimpleNamespace(
                returncode=2,
                stdout="Signature verification completed with warnings",
                stderr="",
            )
            with self.assertRaises(SignatureError):
                self._verify(artifact, self._valid_payload(), signtool_result=warning)

    def test_ignores_undocumented_signtool_stdout_when_exit_status_is_success(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "artifact.msi"
            artifact.write_bytes(b"signed-with-rfc3161-timestamp")
            identity = self._verify(
                artifact,
                self._valid_payload(),
                signtool_result=SimpleNamespace(
                    returncode=0,
                    stdout="any future SignTool diagnostic format",
                    stderr="",
                ),
            )
            self.assertEqual(identity.timestamp_common_name, "Trusted RFC3161 TSA")

    def test_rejects_unavailable_signtool(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "artifact.msi"
            artifact.write_bytes(b"signed-with-rfc3161-timestamp")
            powershell_result = SimpleNamespace(
                returncode=0,
                stdout=json.dumps(self._valid_payload()),
                stderr="",
            )
            runner = Mock(side_effect=[powershell_result, OSError("not found")])
            with self.assertRaises(SignatureError):
                verify_authenticode(
                    artifact,
                    POLICY.publisher_common_name,
                    require_timestamp=True,
                    runner=runner,
                    powershell="powershell.exe",
                    signtool="signtool.exe",
                )

    @unittest.skipUnless(
        sys.platform == "win32",
        "requires Windows CryptoAPI and Authenticode cmdlets",
    )
    def test_windows_inspector_reads_real_embedded_pkcs7_without_timestamp(self):
        """Exercise CryptoAPI against a real temporary Authenticode fixture."""

        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "clarify-inspector-fixture.ps1"
            fixture.write_text("Write-Output signed-fixture\n", encoding="utf-16")
            command = (
                "$ErrorActionPreference='Stop';"
                "$env:PSModulePath=(($env:WINDIR + "
                "'\\System32\\WindowsPowerShell\\v1.0\\Modules') + ';' + "
                "($env:ProgramFiles + '\\WindowsPowerShell\\Modules'));"
                "$source=@'\n" + _AUTHENTICODE_TIMESTAMP_INSPECTOR + "\n'@;"
                "Add-Type -TypeDefinition $source -Language CSharp;"
                "$setSignatureCommand=Get-Command "
                "Set-AuthenticodeSignature -ErrorAction Stop;"
                "$newCertificateCommand=Get-Command "
                "New-SelfSignedCertificate -ErrorAction Stop;"
                "if(-not (Get-PSDrive -Name Cert -ErrorAction SilentlyContinue)){"
                "throw 'Certificate provider is unavailable'};"
                "$fixture=$env:CLARIFY_INSPECTOR_FIXTURE;"
                "$certificate=$null;"
                "try{"
                "$certificate=& $newCertificateCommand.Name "
                "-Subject 'CN=Clarify Inspector Fixture' "
                "-Type CodeSigningCert -CertStoreLocation Cert:\\CurrentUser\\My;"
                "$signed=& $setSignatureCommand.Name -LiteralPath $fixture "
                "-Certificate $certificate;"
                "if($signed.Status -eq 'NotSigned'){throw 'fixture was not signed'};"
                "$protocol=[ClarifyTimestampInspector]::"
                "GetTimestampProtocol($fixture);"
                "if($protocol -cne 'Missing'){throw "
                "('unexpected protocol: ' + $protocol)};"
                "Write-Output $protocol;"
                "}finally{"
                "if($certificate){Remove-Item -LiteralPath "
                "('Cert:\\CurrentUser\\My\\' + $certificate.Thumbprint) "
                "-ErrorAction SilentlyContinue};"
                "Remove-Item -LiteralPath $fixture -Force -ErrorAction SilentlyContinue"
                "}"
            )
            environment = os.environ.copy()
            environment["CLARIFY_INSPECTOR_FIXTURE"] = str(fixture)
            # PowerShell 7 is the default GitHub Actions shell, but the
            # Authenticode cmdlets used by this fixture are provided by the
            # Windows PowerShell 5.1 Security module.  Invoke that binary
            # explicitly while retaining -NoProfile so module autoloading is
            # exercised deterministically.
            powershell_executable = str(
                Path(os.environ.get("SystemRoot", r"C:\Windows"))
                / "System32"
                / "WindowsPowerShell"
                / "v1.0"
                / "powershell.exe"
            )
            result = subprocess.run(
                [
                    powershell_executable,
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    command,
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "Missing")

    def test_rejects_invalid_timestamp_certificate(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "artifact.msi"
            artifact.write_bytes(b"signed-with-invalid-timestamp-certificate")
            with self.assertRaises(SignatureError):
                self._verify(
                    artifact,
                    self._valid_payload(
                        TimestampThumbprint="not-a-thumbprint",
                    ),
                )

    def test_rejects_mismatched_authenticode_publisher(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "artifact.msi"
            artifact.write_bytes(b"signed-by-wrong-publisher")
            with self.assertRaises(SignatureError):
                self._verify(
                    artifact,
                    self._valid_payload(
                        CommonName="Someone Else",
                    ),
                )

    def test_rejects_invalid_primary_signature(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "artifact.msi"
            artifact.write_bytes(b"unsigned")
            with self.assertRaises(SignatureError):
                self._verify(
                    artifact,
                    self._valid_payload(
                        Status="NotSigned",
                        StatusMessage="Unsigned",
                        CommonName="",
                        Thumbprint="",
                        TimestampStatus="Missing",
                        TimestampProtocol="Missing",
                        TimestampCommonName="",
                        TimestampThumbprint="",
                    ),
                )


if __name__ == "__main__":
    unittest.main()
