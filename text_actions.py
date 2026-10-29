"""Validated text definitions and device routes. Credentials stay with providers."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from hotkey_config import HotkeyAction, HotkeyDefinition, HotkeySettings
from workflow_config import (
    WorkflowRoute,
    validate_workflow_route,
    DEFAULT_WORKFLOW_PROMPTS,
)

MAX_ACTIONS = 64
MAX_LIBRARY_BYTES = 256 * 1024
MAX_INPUT_BYTES = 16000
MAX_OUTPUT_BYTES = 64000
MAX_REVISION = (1 << 63) - 1
TEXT_LANGUAGES = frozenset({"auto", "pt", "en", "es", "de", "ru"})
DEFINITION_FIELDS = frozenset({"id", "name", "prompt", "kind", "enabled"})
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z", re.ASCII)
_COMPUTER_LANGUAGE = re.compile(r"[A-Za-z-]{1,32}\Z", re.ASCII)


class TextActionInputPolicy(Enum):
    STANDARD = "standard"
    PAIRED_COMPUTER = "paired_computer"


def validate_input(text, language="auto", *, policy=TextActionInputPolicy.STANDARD):
    if not isinstance(policy, TextActionInputPolicy):
        raise ValueError("Invalid text action input policy")
    maximum = (
        32768 if policy is TextActionInputPolicy.PAIRED_COMPUTER else MAX_INPUT_BYTES
    )
    if type(text) is not str or not text.strip() or len(text.encode("utf-8")) > maximum:
        raise ValueError(f"Text action input must contain 1 to {maximum} UTF-8 bytes")
    if type(language) is not str or (
        not _COMPUTER_LANGUAGE.fullmatch(language)
        if policy is TextActionInputPolicy.PAIRED_COMPUTER
        else language not in TEXT_LANGUAGES
    ):
        raise ValueError("Invalid text action language")


def validate_output(text):
    if (
        type(text) is not str
        or not text.strip()
        or len(text.encode("utf-8")) > MAX_OUTPUT_BYTES
    ):
        raise ValueError("Invalid text action output")
    return text


def identity(value):
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError("Invalid text action ID")
    return value


def opaque(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class TextAction:
    id: str
    name: str
    prompt: str
    kind: str = "custom"
    enabled: bool = True
    revision: int = 1
    processing_profile_id: str = "default"
    shortcut: HotkeyDefinition | None = None

    def __post_init__(self):
        identity(self.id)
        if type(self.name) is not str or not self.name.strip() or len(self.name) > 80:
            raise ValueError("Text action name must contain 1 to 80 characters")
        if (
            type(self.prompt) is not str
            or not self.prompt.strip()
            or len(self.prompt.encode("utf-8")) > 8192
        ):
            raise ValueError("Text action prompt must contain 1 to 8192 UTF-8 bytes")
        if (
            type(self.kind) is not str
            or self.kind not in {"rewrite", "translation", "custom"}
            or type(self.enabled) is not bool
        ):
            raise ValueError("Invalid text action kind or enabled state")
        if type(self.revision) is not int or not 1 <= self.revision <= MAX_REVISION:
            raise ValueError("Invalid text action revision")
        identity(self.processing_profile_id)
        if self.shortcut is not None and not isinstance(
            self.shortcut, HotkeyDefinition
        ):
            raise ValueError("Invalid text action shortcut")

    def definition(self):
        return {key: getattr(self, key) for key in DEFINITION_FIELDS}

    def to_mapping(self):
        return {
            **self.definition(),
            "revision": self.revision,
            "processingProfileId": self.processing_profile_id,
            "shortcut": self.shortcut.to_mapping() if self.shortcut else None,
        }

    @classmethod
    def from_mapping(cls, value, *, definition_only=False):
        allowed = DEFINITION_FIELDS | {"revision"}
        if not definition_only:
            allowed |= {"processingProfileId", "shortcut"}
        if (
            type(value) is not dict
            or set(value) - allowed
            or not DEFINITION_FIELDS <= set(value)
        ):
            raise ValueError("Invalid text action fields")
        shortcut = value.get("shortcut")
        if shortcut is not None and (
            type(shortcut) is not dict or set(shortcut) != {"modifiers", "key"}
        ):
            raise ValueError("Invalid text action shortcut fields")
        return cls(
            **{key: value[key] for key in DEFINITION_FIELDS},
            revision=value.get("revision", 1),
            processing_profile_id=value.get("processingProfileId", "default"),
            shortcut=HotkeyDefinition.from_mapping(shortcut)
            if shortcut is not None
            else None,
        )


def validate_library(actions):
    actions = tuple(actions)
    if len(actions) > MAX_ACTIONS or len({action.id for action in actions}) != len(
        actions
    ):
        raise ValueError("Text library has duplicate IDs or more than 64 actions")
    if (
        len(
            json.dumps(
                {
                    "revision": 0,
                    "actions": [
                        {**action.definition(), "revision": action.revision}
                        for action in actions
                    ],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        > MAX_LIBRARY_BYTES
    ):
        raise ValueError("Text library exceeds 256 KiB")
    return actions


def read_library(value):
    if (
        type(value) is not dict
        or set(value) != {"revision", "actions"}
        or type(value["revision"]) is not int
        or not 0 <= value["revision"] <= MAX_REVISION
        or type(value["actions"]) is not list
    ):
        raise ValueError("Invalid text library response")
    if any(
        type(item) is not dict or set(item) != DEFINITION_FIELDS | {"revision"}
        for item in value["actions"]
    ):
        raise ValueError("Invalid text action read fields")
    if (
        len(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        > MAX_LIBRARY_BYTES
    ):
        raise ValueError("Text library exceeds 256 KiB")
    actions = validate_library(
        TextAction.from_mapping(item, definition_only=True) for item in value["actions"]
    )
    return value["revision"], actions


@dataclass(frozen=True)
class TextActionProfile:
    id: str
    route: WorkflowRoute
    source_scope: str = ""

    def __post_init__(self):
        identity(self.id)
        if self.source_scope not in {"", "refinement", "rewrite", "translation"}:
            raise ValueError("Invalid text profile source")

    def resolved(self, config):
        route = config.workflow(self.source_scope) if self.source_scope else self.route
        return validate_workflow_route(route, "rewrite")

    def to_mapping(self):
        return {
            "id": self.id,
            "route": self.route.to_mapping(),
            "sourceScope": self.source_scope,
        }


@dataclass(frozen=True)
class TextActionSettings:
    actions: tuple[TextAction, ...] = ()
    profiles: tuple[TextActionProfile, ...] = ()
    revision: int = 0
    # Account metadata stays remote. Only device preferences are stored here.
    devices: Mapping[str, Any] = field(default_factory=dict)
    after_dictation: Mapping[str, Any] = field(default_factory=dict)
    action_revisions: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self):
        validate_library(self.actions)
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("Invalid text library revision")
        if len(self.profiles) > 64 or len({p.id for p in self.profiles}) != len(
            self.profiles
        ):
            raise ValueError("Invalid text profiles")
        if self.profiles:
            for action in self.actions:
                self.profile(action.processing_profile_id)

    def action(self, action_id):
        return next((action for action in self.actions if action.id == action_id), None)

    def profile(self, profile_id):
        for profile in self.profiles:
            if profile.id == profile_id:
                return profile
        raise ValueError("Unknown text processing profile")

    def to_mapping(self):
        return {
            "actions": [a.to_mapping() for a in self.actions],
            "profiles": [p.to_mapping() for p in self.profiles],
            "revision": self.revision,
            "devices": dict(self.devices),
            "afterDictation": dict(self.after_dictation),
            "actionRevisions": dict(self.action_revisions),
        }

    @classmethod
    def migrate(cls, workflows, hotkeys):
        profiles = [TextActionProfile("default", workflows.refinement, "refinement")]
        actions = []
        for action_id, name, key in (
            ("rewrite", "Rewrite", HotkeyAction.REWRITE),
            ("translation", "Translation", HotkeyAction.TRANSLATION),
        ):
            route = workflows.route(action_id)
            profile_id = "legacy-" + action_id
            profiles.append(TextActionProfile(profile_id, route, action_id))
            actions.append(
                TextAction(
                    action_id,
                    name,
                    route.prompt or DEFAULT_WORKFLOW_PROMPTS[action_id],
                    action_id,
                    route.enabled,
                    processing_profile_id=profile_id,
                    shortcut=hotkeys.definition(key),
                )
            )
        return cls(tuple(actions), tuple(profiles))

    @classmethod
    def from_mapping(cls, value, workflows, hotkeys):
        if not isinstance(value, Mapping):
            return cls.migrate(workflows, hotkeys)
        return cls(
            tuple(TextAction.from_mapping(a) for a in value.get("actions", [])),
            tuple(
                TextActionProfile(
                    p["id"],
                    WorkflowRoute.from_mapping(p["route"]),
                    p.get("sourceScope", ""),
                )
                for p in value.get("profiles", [])
            ),
            value.get("revision", 0),
            value.get("devices", {}),
            value.get("afterDictation", {}),
            value.get("actionRevisions", {}),
        )


def settings_for(config):
    return (
        config.text_actions
        if config.text_actions is not None
        else TextActionSettings.migrate(config.workflows, config.hotkeys)
    )


def native_bindings(config, actions):
    """Replace legacy text keys with the active catalog, in one validated set."""
    base = {
        key: value
        for key, value in config.hotkeys.hotkeys.items()
        if key not in {HotkeyAction.REWRITE, HotkeyAction.TRANSLATION}
    }
    for action in actions:
        if action.enabled and action.shortcut is not None:
            base["text_action:" + action.id] = action.shortcut
    return HotkeySettings(base, config.hotkeys.activation_mode, closed=True)


@dataclass(frozen=True)
class TextActionSnapshot:
    action: TextAction
    route: WorkflowRoute | None
    connection: Any = None
    account_context: Any = None
    operation_id: str = ""
    context: str = ""
    config: Any = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class DictationTextActionSnapshot:
    action: TextActionSnapshot | None
    language: str
    context: str
    account_context: Any = None
    config: Any = field(default=None, repr=False, compare=False)
    action_error: str = ""
