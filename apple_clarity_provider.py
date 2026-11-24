"""Text-only adapter for the packaged Apple Foundation Models helper."""

from __future__ import annotations

import json
from pathlib import Path
import platform
import subprocess
import sys
import time

from provider_adapters import ProviderAdapter
from provider_http import ProviderTimeoutError
from provider_types import (
    ModelCatalog,
    ProviderCapability,
    ProviderConfigurationError,
    ProviderMetadata,
    ProviderResponseError,
    RewriteResult,
)


PROVIDER_ID = "apple_clarity"
MODEL_ID = "apple-on-device"
MODEL_LABEL = "Apple on-device model"
UNAVAILABLE = "Apple Intelligence is unavailable. Check System Settings."
METADATA = ProviderMetadata(
    provider_id=PROVIDER_ID,
    display_name="Apple Intelligence",
    capabilities=frozenset(
        {ProviderCapability.TEXT_GENERATION, ProviderCapability.MODEL_DISCOVERY}
    ),
    default_base_url="",
    audio_model_key="apple_clarity_audio_model",
    text_model_key="apple_clarity_text_model",
    default_audio_model="",
    default_text_model=MODEL_ID,
    authentication="on_device",
)


def supported_platform() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


class AppleClarityAdapter(ProviderAdapter):
    def __init__(self, http, *, executable: Path | None = None):
        super().__init__(METADATA, http)
        self._executable = executable

    def _helper(self) -> Path:
        if self._executable is not None:
            return self._executable
        if supported_platform():
            base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent / "build/macos"))
            helper = base / "clarify-apple-clarity"
            if helper.is_file():
                return helper
        raise ProviderConfigurationError(PROVIDER_ID, UNAVAILABLE)

    def _call(self, command, cancel, *, payload=None, timeout):
        operation = "model_discovery" if command == "status" else "text_generation"
        if cancel is not None:
            cancel.raise_if_cancelled(PROVIDER_ID, operation)
        data = (
            json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
        )
        try:
            process = subprocess.Popen(
                [str(self._helper()), command],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            raise ProviderConfigurationError(PROVIDER_ID, UNAVAILABLE) from error

        deadline = time.monotonic() + timeout
        try:
            while True:
                if cancel is not None:
                    cancel.raise_if_cancelled(PROVIDER_ID, operation)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProviderTimeoutError(
                        provider=PROVIDER_ID, operation=operation
                    )
                try:
                    stdout, _ = process.communicate(data, timeout=min(remaining, 0.05))
                except subprocess.TimeoutExpired:
                    data = None
                else:
                    break
            if cancel is not None:
                cancel.raise_if_cancelled(PROVIDER_ID, operation)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()

        if process.returncode:
            raise ProviderResponseError(
                PROVIDER_ID, "Apple Intelligence could not respond."
            )
        try:
            result = json.loads(stdout)
        except (UnicodeDecodeError, ValueError):
            result = None
        if not isinstance(result, dict):
            raise ProviderResponseError(
                PROVIDER_ID, "Apple Intelligence could not respond."
            )
        if result.get("status") == "unavailable":
            raise ProviderConfigurationError(PROVIDER_ID, UNAVAILABLE)
        return result

    def validate(self, connection, cancel_token=None, *, operation="validation"):
        result = self._call("status", cancel_token, timeout=2)
        if result.get("status") != "available":
            raise ProviderConfigurationError(PROVIDER_ID, UNAVAILABLE)
        return result

    def discover_models(self, connection, cancel_token=None):
        self.validate(connection, cancel_token)
        return ModelCatalog(
            text_models=(MODEL_ID,), display_names={MODEL_ID: MODEL_LABEL}
        )

    def rewrite(self, request, connection, cancel_token=None):
        if request.model != MODEL_ID:
            raise ProviderConfigurationError(
                PROVIDER_ID, "Choose the Apple on-device model."
            )
        result = self._call(
            "rewrite",
            cancel_token,
            payload={
                "instruction": request.instruction,
                "source": request.source_message,
            },
            timeout=15,
        )
        text = result.get("text")
        if (
            result.get("status") != "ok"
            or not isinstance(text, str)
            or not text.strip()
        ):
            raise ProviderResponseError(
                PROVIDER_ID, "Apple Intelligence could not rewrite the text."
            )
        # A final question mark may be followed by a closing quote or bracket.
        question_marks = ("?", "？")
        closing = " \t\r\n\"'”’»)]}"
        if request.text.rstrip(closing).endswith(question_marks) and not text.rstrip(
            closing
        ).endswith(question_marks):
            raise ProviderResponseError(
                PROVIDER_ID, "Apple Intelligence changed a question."
            )
        return RewriteResult(text.strip(), PROVIDER_ID, MODEL_ID)
