"""Reject extreme content loss before a faithful edit can replace its source.

This is a conservative size check, not a semantic completeness test. Custom
transformations such as summaries must not use it.
"""

import re


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def is_exact_duplicate_removal(source: str, result: str) -> bool:
    sentences = [
        _normalized(sentence)
        for sentence in re.split(r"(?<=[.!?。！？])\s+|\n+", source.strip())
        if sentence.strip()
    ]
    unique = list(dict.fromkeys(sentences))
    return len(unique) < len(sentences) and _normalized(result) == " ".join(unique)


def validate_preserved_text(source: str, result: str) -> None:
    """Allow ordinary edits and exact deduplication, but reject summary-sized output."""
    original, edited = _normalized(source), _normalized(result)
    if len(original) < 240 or len(edited) * 4 >= len(original):
        return
    if is_exact_duplicate_removal(source, result):
        return
    raise ValueError("Transformation removed most of the source")
