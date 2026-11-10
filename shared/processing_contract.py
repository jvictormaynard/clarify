"""Wire capabilities derived from the existing processing policy owners."""

from shared.dictation_policy import DictationCleanupLevel
from shared.output_preferences import LANGUAGES
from shared.writing_style_policy import WritingStyle

CONTRACT = {
    "schema_version": 1,
    "output_languages": ["auto", *LANGUAGES],
    "writing_styles": [style.value for style in WritingStyle],
    "cleanup_levels": [level.value for level in DictationCleanupLevel],
    "dictation_actions": True,
    "explicit_dictation_policy": True,
    "limits": {
        "account": {"text_input_bytes": 16000, "text_output_bytes": 64000},
        "computer": {"text_input_bytes": 32768, "text_output_bytes": 32768},
    },
    "errors": {
        "operation_in_progress": "wait",
        "operation_pending": "wait",
        "busy": "wait",
        "operation_cancelled": "new_operation",
        "operation_conflict": "new_operation",
        "operation_expired": "new_operation",
        "result_unavailable": "new_operation",
        "operation_in_future": "check_clock",
        "operation_limit": "wait",
        "operation_history_full": "reconnect",
        "text_action_missing": "refresh_actions",
        "text_action_disabled": "refresh_actions",
        "text_action_stale": "refresh_actions",
        "not_ready": "configure",
        "processing_failed": "new_operation",
        "authentication_required": "authenticate",
        "action_changed": "refresh_actions",
    },
}


def capabilities(destination, *, dictation_editing=None):
    return {
        **{
            key: value
            for key, value in CONTRACT.items()
            if key not in {"limits", "errors"}
        },
        **CONTRACT["limits"][destination],
        "dictation_editing": dictation_editing
        if dictation_editing is not None
        else dict.fromkeys(
            (
                "legacy",
                "natural",
                "clarity",
                "action",
                "legacy_translated",
                "natural_translated",
            ),
            destination == "account",
        ),
    }
