"""Immutable writing-style choices for captured Windows application targets.

This boundary resolves executable paths and refinement eligibility. Callers
own target capture, persistence, cleanup policy, prompts, and actual results.
"""

from __future__ import annotations

import ntpath
from dataclasses import dataclass, replace
from enum import Enum


MAX_APPLICATION_STYLE_RULES = 32


class WritingStyle(str, Enum):
    """Presentation choices, independent of cleanup depth and provider routes."""

    NATURAL = "natural"
    INFORMAL = "informal"
    ORGANIZED = "organized"


class WritingStyleDecisionReason(str, Enum):
    DEFAULT = "default"
    SELECTED = "selected"
    REFINEMENT_NOT_ALLOWED = "refinement_not_allowed"


class WritingStyleConfigurationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def windows_executable_key(executable: str | None) -> str | None:
    """Return a lexical Windows key without inspecting the filesystem.

    Relative paths, device namespaces, streams, and ambiguous path components
    have no identity. Unicode normalization and case folding beyond Windows
    ``normcase`` would merge distinct executable paths, so neither is used.
    """

    if not isinstance(executable, str) or not 0 < len(executable) <= 32767:
        return None
    candidate = executable.replace("/", "\\")
    if any(ord(char) < 32 or char in '<>"|?*' for char in candidate):
        return None
    drive, tail = ntpath.splitdrive(candidate)
    if drive.startswith("\\\\"):
        drive_parts = drive[2:].split("\\")
        if len(drive_parts) != 2 or not all(drive_parts) or ":" in drive:
            return None
    elif not (
        len(drive) == 2
        and drive[0] in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        and drive[1] == ":"
    ):
        return None
    if not tail.startswith("\\") or ":" in tail:
        return None
    components = candidate.split("\\")
    if any(
        part in {".", ".."} or part.endswith((" ", ".")) for part in components if part
    ):
        return None
    if ntpath.splitext(tail)[1].lower() != ".exe":
        return None
    return ntpath.normcase(ntpath.normpath(candidate))


@dataclass(frozen=True)
class WritingStyleDecision:
    """Eligibility for a refinement step, without claiming actual application."""

    style: WritingStyle | None
    reason: WritingStyleDecisionReason


@dataclass(frozen=True)
class WritingStyleSelection:
    """A rule snapshot for the executable captured at operation start."""

    executable: str | None = None
    requested_style: WritingStyle | None = None

    def for_refinement(self, *, generative_allowed: bool) -> WritingStyleDecision:
        """Use permission from the existing workflow; never grant permission."""

        if not isinstance(generative_allowed, bool):
            raise TypeError("generative_allowed_must_be_boolean")
        if self.requested_style is None:
            return WritingStyleDecision(None, WritingStyleDecisionReason.DEFAULT)
        if not generative_allowed:
            return WritingStyleDecision(
                None, WritingStyleDecisionReason.REFINEMENT_NOT_ALLOWED
            )
        return WritingStyleDecision(
            self.requested_style, WritingStyleDecisionReason.SELECTED
        )


@dataclass(frozen=True)
class ApplicationWritingStyleRule:
    """One validated executable identity and its presentation choice."""

    executable: str
    style: WritingStyle

    def __post_init__(self) -> None:
        key = windows_executable_key(self.executable)
        if key is None:
            raise WritingStyleConfigurationError("invalid_application_executable")
        try:
            style = WritingStyle(self.style)
        except (TypeError, ValueError) as error:
            raise WritingStyleConfigurationError("invalid_writing_style") from error
        object.__setattr__(self, "executable", key)
        object.__setattr__(self, "style", style)


@dataclass(frozen=True)
class ApplicationWritingStyles:
    """A bounded immutable rule set; no rule means no style override."""

    rules: tuple[ApplicationWritingStyleRule, ...] = ()

    def __post_init__(self) -> None:
        try:
            rules = tuple(self.rules)
        except TypeError as error:
            raise WritingStyleConfigurationError("invalid_application_rule") from error
        if len(rules) > MAX_APPLICATION_STYLE_RULES:
            raise WritingStyleConfigurationError("too_many_application_rules")
        if any(not isinstance(rule, ApplicationWritingStyleRule) for rule in rules):
            raise WritingStyleConfigurationError("invalid_application_rule")
        keys = {rule.executable for rule in rules}
        if len(keys) != len(rules):
            raise WritingStyleConfigurationError("duplicate_application_rule")
        object.__setattr__(self, "rules", rules)

    def with_rule(
        self, executable: str, style: WritingStyle | None
    ) -> ApplicationWritingStyles:
        """Return an updated rule set. None removes an existing override."""

        key = windows_executable_key(executable)
        if key is None:
            raise WritingStyleConfigurationError("invalid_application_executable")
        if style is None:
            return replace(
                self, rules=tuple(rule for rule in self.rules if rule.executable != key)
            )
        updated_rule = ApplicationWritingStyleRule(key, style)
        if any(rule.executable == key for rule in self.rules):
            rules = tuple(
                updated_rule if rule.executable == key else rule for rule in self.rules
            )
        else:
            rules = self.rules + (updated_rule,)
        return replace(self, rules=rules)

    def resolve(self, executable: str | None) -> WritingStyleSelection:
        """Resolve a captured path once; later rule edits cannot alter the value."""

        key = windows_executable_key(executable)
        for rule in self.rules:
            if rule.executable == key:
                return WritingStyleSelection(key, rule.style)
        return WritingStyleSelection(key)
