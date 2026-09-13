"""Run via the Windows desktop shell to verify the non-virtualized profile.

This read-only probe emits status only, never keys, vocabulary or transcripts.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from local_asr_catalog import installer_for, MODELS
from clarify.desktop.qml_runtime import create_runtime_repositories
from dictionary_snippets import (
    DictionarySnippetService,
    LocalDictionarySnippetsRepository,
)


def main():
    report = {}
    try:
        repositories = create_runtime_repositories()
        config = repositories.config.load()
        route = config.workflow("transcription")
        report["config_path"] = str(repositories.config.path)
        report["transcription"] = {
            "provider": route.provider_id,
            "model": route.model_id,
        }
        report["keys_available"] = {
            provider: bool(getattr(config, provider).api_key)
            for provider in ("gemini", "openai", "groq")
        }
        service = DictionarySnippetService(
            LocalDictionarySnippetsRepository(
                Path(repositories.config.path).parent / "dictionary.json"
            )
        )
        report["dictionary_terms"] = len(service.state.dictionary)
        report["models"] = {
            model: installer_for(model, "cpu").status()["state"] for model in MODELS
        }
        report["medium_gpu"] = installer_for("ggml-medium", "cuda:0").status()["state"]
        report["ok"] = all(value == "installed" for value in report["models"].values())
        if len(sys.argv) > 2:
            from clarify.desktop.qml_runtime import QtWorkflowConfig, QtProviderGateway
            from workflows import RecordingSnapshot
            from provider_registry import PROVIDER_REGISTRY

            audio = Path(sys.argv[2])
            try:
                result = QtProviderGateway(
                    QtWorkflowConfig(repositories), service
                ).transcribe(
                    RecordingSnapshot(audio, audio.read_bytes()), "prompt", "en"
                )
                report["transcription_succeeded"] = bool(result.text.strip())
                report["refinement_failed"] = result.refinement_failed
                report["ok"] = (
                    report["ok"]
                    and bool(result.text.strip())
                    and not result.refinement_failed
                )
            finally:
                PROVIDER_REGISTRY.shutdown()
    except Exception as error:
        report["error_type"] = type(error).__name__
        report["ok"] = False
    Path(sys.argv[1]).write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
