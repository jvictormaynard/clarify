"""Account-isolated action snapshots and rollback-capable desktop transactions."""

from __future__ import annotations

from contextlib import nullcontext
from collections.abc import Callable
from dataclasses import dataclass, field, replace
import json
import threading
import uuid

from clarify_account import AccountError, TextActionsConflict
from text_actions import (
    TextAction,
    TextActionSnapshot,
    DictationTextActionSnapshot,
    native_bindings,
    opaque,
    read_library,
    settings_for,
    validate_library,
)
from workflow_config import validate_workflow_route
from shared.dictation_policy import DictationCleanupPolicy, cleanup_level
from provider_types import ProviderCapability, ProviderConnection
from provider_registry import PROVIDER_REGISTRY


class TextActionStateChanged(ValueError):
    code = "text_actions_conflict"


@dataclass(frozen=True)
class TextProfileModelRequest:
    profile_id: str
    provider_id: str
    endpoint: str
    context: str
    revision: str
    connection: ProviderConnection = field(repr=False)
    cache_key: tuple = field(repr=False)
    request_key: str
    account_id: str = ""
    account_generation: int = 0
    status: str = "idle"
    draft_endpoint: bool = False


@dataclass
class TextActionMutation:
    """One reserved transaction. Network phases never own UI or snapshot locks."""

    context: str
    revision: str
    owner: object
    before: object
    actions: tuple
    new_actions: tuple
    library_revision: int
    candidate: object
    remote: bool
    validate: Callable[[], None] | None = field(default=None, repr=False)
    accepted: object = None
    restored: object = None
    error: Exception | None = None
    incomplete: bool = False
    committed: bool = False
    abandoned: threading.Event = field(default_factory=threading.Event)
    decision: threading.Event = field(default_factory=threading.Event)


class TextActionService:
    def __init__(
        self, repository, account=None, *, apply_bindings=None, chatgpt_session=None
    ):
        self.repository = repository
        self.account = account
        self.apply_bindings = apply_bindings
        self.chatgpt_session = chatgpt_session
        self._lock = threading.RLock()
        self._libraries = {}
        self._incomplete = False
        self._pending = None
        self._refresh_generation = 0

    def managed(self):
        return self.account is not None and any(
            getattr(self.account, key, False) is True
            for key in ("managed", "signed_in", "hosted")
        )

    def owner(self):
        if not self.managed():
            return None
        owner = self.account.history_identity()
        if owner is None:
            raise AccountError(
                "Entre na conta novamente.", code="authentication_required"
            )
        return owner

    def context(self):
        owner = self.owner()
        if owner is not None:
            return opaque([owner.endpoint, owner.user_id, owner.generation])
        return opaque(
            [
                "personal",
                getattr(self.account, "_generation", 0),
                getattr(self.account, "default_endpoint", ""),
                getattr(self.account, "_state", {}).get("endpoint", ""),
            ]
        )

    def _device_key(self):
        owner = self.owner()
        return (
            opaque([owner.endpoint, owner.user_id]) if owner is not None else "personal"
        )

    def _library(self):
        account_guard = getattr(self.account, "_lock", None) or nullcontext()
        config_guard = getattr(self.repository, "_lock", None) or nullcontext()
        with account_guard, config_guard:
            return self._library_owned()

    def _library_owned(self):
        owner = self.owner()
        if owner is None:
            config = settings_for(self.repository.load())
            return config.revision, config.actions
        context = self.context()
        if context not in self._libraries:
            path = self.account.text_actions_path(owner)
            try:
                self._libraries[context] = read_library(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except FileNotFoundError:
                raise AccountError(
                    "Atualize as ações da conta.", code="text_actions_unavailable"
                ) from None
        revision, actions = self._libraries[context]
        preferences = settings_for(self.repository.load()).devices.get(
            self._device_key(), {}
        )
        return revision, tuple(
            replace(
                action,
                processing_profile_id=preferences.get(action.id, {}).get(
                    "processingProfileId", "default"
                ),
                shortcut=TextAction.from_mapping(
                    {**action.to_mapping(), **preferences.get(action.id, {})}
                ).shortcut,
            )
            for action in actions
        )

    def refresh(self, *, cancel=None, apply_bindings=True):
        value = self.fetch_refresh(cancel=cancel)
        return self.publish_refresh(value, apply_bindings=apply_bindings)

    def fetch_refresh(self, *, cancel=None):
        """Capture identity, then perform GET without holding any snapshot lock."""
        account_guard = getattr(self.account, "_lock", None) or nullcontext()
        with self._lock, account_guard:
            owner = self.owner()
            context = self.context()
            self._refresh_generation += 1
            generation = self._refresh_generation
        value = (
            self.account.text_actions(expected_identity=owner, cancel=cancel)
            if owner is not None
            else None
        )
        return generation, context, value

    def publish_refresh(self, result, *, apply_bindings=True):
        account_guard = getattr(self.account, "_lock", None) or nullcontext()
        config_guard = getattr(self.repository, "_lock", None) or nullcontext()
        with self._lock, account_guard, config_guard:
            generation, context, value = result
            if (
                generation != self._refresh_generation
                or context != self.context()
                or self._pending is not None
            ):
                raise ValueError(
                    "As ações ou a conta mudaram. Atualize e tente novamente."
                )
            if value is not None:
                incoming = read_library(value)
                current = self._libraries.get(context)
                if current is not None and incoming[0] < current[0]:
                    raise ValueError("As ações mudaram. Atualize e tente novamente.")
                self._libraries[context] = incoming
            if apply_bindings and self.apply_bindings is not None:
                try:
                    self.apply_bindings(self.bindings())
                except Exception:
                    self._incomplete = True
                    raise
            self._incomplete = False
            return self.projection()

    def projection(self):
        account_guard = getattr(self.account, "_lock", None) or nullcontext()
        config_guard = getattr(self.repository, "_lock", None) or nullcontext()
        with self._lock, account_guard, config_guard:
            config = self.repository.load()
            settings = settings_for(config)
            revision, actions = self._library()
            context = self.context()
            profiles = []
            for profile in settings.profiles:
                if self.managed():
                    continue
                route = profile.resolved(config)
                profiles.append(
                    {
                        "id": profile.id,
                        "name": self.profile_name(profile.id),
                        "providerId": route.provider_id,
                        "modelId": route.model_id,
                        "customEndpoint": route.custom_endpoint,
                        "enabled": route.enabled,
                        "managed": False,
                        "available": self.profile_available(route, config),
                    }
                )
            if self.managed():
                profiles = [
                    {
                        "id": "default",
                        "name": "Clarify",
                        "providerId": "clarify",
                        "modelId": "",
                        "customEndpoint": "",
                        "enabled": True,
                        "managed": True,
                        "available": True,
                    }
                ]
            after = settings.after_dictation.get(self._device_key(), {}).get(
                self.dictation_context(config), {}
            )
            return {
                "textActions": [action.to_mapping() for action in actions],
                "textActionProfiles": profiles,
                "textActionContext": context,
                "textActionsRevision": opaque(
                    [
                        context,
                        revision,
                        settings.to_mapping(),
                        profiles,
                        self.dictation_context(config),
                        config.hotkeys.to_mapping(),
                    ]
                ),
                "afterDictationTextActionId": after.get("id", ""),
                "afterDictationTextActionLanguage": after.get("language", "auto"),
                "textActionDictationContext": self.dictation_context(config),
            }

    def dictation_context(self, config):
        return (
            "local_asr"
            if not self.managed()
            and config.workflow("transcription").provider_id == "local_asr"
            else "cloud"
        )

    def bindings(self):
        return native_bindings(self.repository.load(), self._library()[1])

    def bindings_for(self, config):
        if not self.managed():
            return native_bindings(config, settings_for(config).actions)
        actions = self._library()[1]
        preferences = settings_for(config).devices.get(self._device_key(), {})
        return native_bindings(
            config,
            tuple(
                TextAction.from_mapping({**a.to_mapping(), **preferences.get(a.id, {})})
                for a in actions
            ),
        )

    def _guard(self, context, revision):
        current = self.projection()
        if (
            self._incomplete
            or type(context) is not str
            or context != current["textActionContext"]
            or revision != current["textActionsRevision"]
        ):
            raise TextActionStateChanged(
                "As ações ou a conta mudaram. Atualize e tente novamente."
            )

    def _transaction(
        self,
        mutate,
        context,
        revision,
        *,
        remote=False,
        config_change=None,
        defer_remote=False,
        precommit=None,
    ):
        account_guard = getattr(self.account, "_lock", None) or nullcontext()
        config_guard = getattr(self.repository, "_lock", None) or nullcontext()
        session_guard = getattr(self.chatgpt_session, "_lock", None) or nullcontext()
        with self._lock, account_guard, config_guard, session_guard:
            if self._pending is not None:
                raise ValueError("Aguarde a alteração das ações.")
            require_writable = getattr(self.repository, "require_writable", None)
            if callable(require_writable):
                require_writable()
            self._guard(context, revision)
            before = self.repository.load()
            settings = settings_for(before)
            library_revision, actions = self._library()
            new_settings, new_actions = mutate(settings, actions)
            new_actions = validate_library(new_actions)
            valid_ids = {a.id for a in new_actions if a.enabled}
            after = {
                key: dict(value) for key, value in new_settings.after_dictation.items()
            }
            owner_preferences = dict(after.get(self._device_key(), {}))
            for key, value in owner_preferences.items():
                if value.get("id") and value["id"] not in valid_ids:
                    owner_preferences[key] = {"id": "", "language": "auto"}
            if owner_preferences:
                after[self._device_key()] = owner_preferences
                new_settings = replace(new_settings, after_dictation=after)
            for action in new_actions:
                if not self.managed():
                    new_settings.profile(action.processing_profile_id).resolved(before)
                elif action.processing_profile_id != "default":
                    raise ValueError(
                        "Account actions use the account processing service"
                    )
            native_bindings(before, new_actions)  # Validate collisions before effects.
            owner = self.owner()
            if owner is None:
                revisions = dict(settings.action_revisions)
                for action in (*actions, *new_actions):
                    revisions[action.id] = max(
                        action.revision, revisions.get(action.id, 0)
                    )
                new_settings = replace(
                    new_settings,
                    actions=new_actions,
                    revision=settings.revision + 1,
                    action_revisions=revisions,
                )
            else:
                devices = dict(new_settings.devices)
                devices[self._device_key()] = {
                    a.id: {
                        "processingProfileId": a.processing_profile_id,
                        "shortcut": a.shortcut.to_mapping() if a.shortcut else None,
                    }
                    for a in new_actions
                }
                new_settings = replace(new_settings, devices=devices)
            candidate = replace(before, text_actions=new_settings)
            if config_change is not None:
                candidate = config_change(candidate)
            mutation = TextActionMutation(
                context,
                revision,
                owner,
                before,
                actions,
                new_actions,
                library_revision,
                candidate,
                owner is not None and remote,
                validate=precommit,
            )
            self._pending = mutation
            self._refresh_generation += 1
        if defer_remote and mutation.remote:
            return mutation
        self.send_mutation(mutation)
        self.commit_mutation(mutation)
        self.compensate_mutation(mutation)
        return self.finish_mutation(mutation)

    def send_mutation(self, mutation):
        if not mutation.remote:
            return
        try:
            mutation.accepted = self.account.save_text_actions(
                [a.definition() for a in mutation.new_actions],
                mutation.library_revision,
                expected_identity=mutation.owner,
            )
        except Exception as error:
            mutation.accepted = getattr(error, "accepted_text_actions", None)
            mutation.error = error

    def commit_mutation(self, mutation):
        """Run only on the effects owner (Qt in production). No network calls."""
        account_guard = getattr(self.account, "_lock", None) or nullcontext()
        config_guard = getattr(self.repository, "_lock", None) or nullcontext()
        session_guard = getattr(self.chatgpt_session, "_lock", None) or nullcontext()
        with self._lock, account_guard, config_guard, session_guard:
            applied = False
            try:
                if mutation.abandoned.is_set():
                    raise ValueError("A alteração foi cancelada.")
                if mutation.error is not None:
                    raise mutation.error
                self._guard(mutation.context, mutation.revision)
                if mutation.validate is not None:
                    mutation.validate()
                if self.repository.load() != mutation.before:
                    raise TextActionStateChanged(
                        "As configurações mudaram. Atualize e tente novamente."
                    )
                if self.apply_bindings is not None:
                    applied = True
                    self.apply_bindings(
                        native_bindings(mutation.candidate, mutation.new_actions)
                    )
                self.repository.apply(mutation.candidate)
                if mutation.accepted is not None:
                    self._libraries[mutation.context] = read_library(mutation.accepted)
                mutation.committed = True
            except Exception as error:
                mutation.error = error
                if (
                    isinstance(error, TextActionsConflict)
                    and mutation.context == self.context()
                ):
                    self._libraries[mutation.context] = read_library(error.current)
                    applied = True
                if applied and self.apply_bindings is not None:
                    try:
                        self.apply_bindings(self.bindings_for(self.repository.load()))
                    except Exception:
                        mutation.incomplete = True
            finally:
                mutation.decision.set()

    def compensate_mutation(self, mutation):
        """Remote CAS uses the accepted revision, including an accepted cache failure."""
        if mutation.committed or mutation.accepted is None:
            return
        try:
            mutation.restored = self.account.save_text_actions(
                [a.definition() for a in mutation.actions],
                mutation.accepted["revision"],
                expected_identity=mutation.owner,
            )
        except Exception as error:
            if isinstance(error, TextActionsConflict):
                mutation.restored = error.current
            mutation.incomplete = True

    def finish_mutation(self, mutation, *, apply_bindings=True):
        account_guard = getattr(self.account, "_lock", None) or nullcontext()
        config_guard = getattr(self.repository, "_lock", None) or nullcontext()
        with self._lock, account_guard, config_guard:
            if mutation is not self._pending:
                raise ValueError("A alteração expirou.")
            self._pending = None
            if mutation.restored is not None and mutation.context == self.context():
                previous_bindings = self.bindings()
                self._libraries[mutation.context] = read_library(mutation.restored)
                bindings = self.bindings()
                if (
                    apply_bindings
                    and self.apply_bindings is not None
                    and bindings != previous_bindings
                ):
                    try:
                        self.apply_bindings(bindings)
                    except Exception:
                        mutation.incomplete = True
            self._incomplete = mutation.incomplete
            if mutation.incomplete:
                raise RuntimeError(
                    "Não foi possível restaurar as ações ou os atalhos. Atualize antes de salvar novamente."
                ) from mutation.error
            if mutation.error is not None:
                raise mutation.error
            return self.projection()

    def save(self, value, context, revision, *, defer_remote=False):
        action = TextAction.from_mapping(value)

        def mutate(settings, actions):
            old = next((a for a in actions if a.id == action.id), None)
            updated = replace(
                action,
                processing_profile_id=old.processing_profile_id
                if old is not None and "processingProfileId" not in value
                else action.processing_profile_id,
                shortcut=old.shortcut
                if old is not None and "shortcut" not in value
                else action.shortcut,
                revision=old.revision + (old.definition() != action.definition())
                if old
                else settings.action_revisions.get(action.id, 0) + 1,
            )
            return settings, tuple(
                updated if a.id == action.id else a for a in actions
            ) if old else (*actions, updated)

        return self._transaction(
            mutate, context, revision, remote=True, defer_remote=defer_remote
        )

    def delete(self, action_id, context, revision, *, defer_remote=False):
        def mutate(settings, actions):
            if not any(a.id == action_id for a in actions):
                raise ValueError("Unknown text action")
            return settings, tuple(a for a in actions if a.id != action_id)

        return self._transaction(
            mutate, context, revision, remote=True, defer_remote=defer_remote
        )

    def duplicate(self, action_id, context, revision, *, defer_remote=False):
        self._guard(context, revision)
        action = next((a for a in self._library()[1] if a.id == action_id), None)
        if action is None:
            raise ValueError("Unknown text action")
        return self.save(
            replace(
                action,
                id=str(uuid.uuid4()),
                name=(action.name[:73] + " (copy)"),
                revision=1,
                shortcut=None,
            ).to_mapping(),
            context,
            revision,
            defer_remote=defer_remote,
        )

    def profile_model_request(
        self, profile_id, provider_id, endpoint, context, revision
    ):
        """Resolve a draft's discovery identity without selecting or editing a route."""
        account_guard = getattr(self.account, "_lock", None) or nullcontext()
        config_guard = getattr(self.repository, "_lock", None) or nullcontext()
        with self._lock, account_guard, config_guard:
            self._guard(context, revision)
            if self.managed():
                raise ValueError(
                    "Account processing profiles are managed by the service"
                )
            config = self.repository.load()
            before = settings_for(config).profile(profile_id).resolved(config)
            metadata = PROVIDER_REGISTRY.describe(provider_id)
            if not metadata.supports(
                ProviderCapability.TEXT_GENERATION
            ) or not metadata.supports(ProviderCapability.MODEL_DISCOVERY):
                raise ValueError("This provider does not support text model discovery")
            route = validate_workflow_route(
                replace(
                    before,
                    provider_id=provider_id,
                    model_id=metadata.default_text_model,
                    custom_endpoint=endpoint,
                    account_id="",
                ),
                "rewrite",
            )
            account_id, generation, status = "", 0, "idle"
            if provider_id == "chatgpt":
                state = (
                    self.chatgpt_session.snapshot()
                    if self.chatgpt_session is not None
                    else {}
                )
                account_id = (
                    before.account_id
                    if before.provider_id == "chatgpt"
                    else state.get("accountId", "")
                )
                generation = state.get("generation", 0)
                if (
                    not state.get("connected")
                    or not state.get("planEnabled")
                    or not account_id
                ):
                    status = "not_configured"
                elif account_id != state.get("accountId"):
                    status = "account_mismatch"
                connection = ProviderConnection(
                    "", metadata.default_base_url, account_id
                )
                cache_key = (provider_id, account_id, str(generation))
            else:
                provider = getattr(config, provider_id)
                connection = ProviderConnection(
                    provider.api_key.strip(),
                    route.custom_endpoint
                    or provider.base_url
                    or metadata.default_base_url,
                )
                cache_key = (provider_id, connection.base_url, connection.api_key)
                if not connection.api_key:
                    status = "not_configured"
            return TextProfileModelRequest(
                profile_id,
                provider_id,
                route.custom_endpoint,
                context,
                revision,
                connection,
                cache_key,
                opaque(
                    [profile_id, context, revision, cache_key, route.custom_endpoint]
                ),
                account_id,
                generation,
                status,
                route.custom_endpoint
                != (
                    before.custom_endpoint if provider_id == before.provider_id else ""
                ),
            )

    def save_profile(self, value, context, revision, *, model_catalog=None):
        if self.managed():
            raise ValueError("Account processing profiles are managed by the service")
        required = {"id", "providerId", "modelId", "customEndpoint", "enabled"}
        if (
            type(value) is not dict
            or not required <= set(value)
            or set(value) - (required | {"name", "managed", "available"})
        ):
            raise ValueError("Invalid text profile fields")
        if (
            any(
                type(value[key]) is not str
                for key in ("id", "providerId", "modelId", "customEndpoint")
            )
            or type(value["enabled"]) is not bool
            or any(
                type(value[key]) is not bool
                for key in ("managed", "available")
                if key in value
            )
        ):
            raise ValueError("Invalid text profile types")
        if value.get("managed", False) or (
            "name" in value and value["name"] != self.profile_name(value["id"])
        ):
            raise ValueError("Text profile identity is read-only")
        changed_route = {}

        def mutate(settings, actions):
            profile = settings.profile(value["id"])
            before = profile.resolved(self.repository.load())
            account_id = (
                before.account_id if value["providerId"] == before.provider_id else ""
            )
            if value["providerId"] == "chatgpt" and before.provider_id != "chatgpt":
                state = (
                    self.chatgpt_session.snapshot()
                    if self.chatgpt_session is not None
                    else {}
                )
                if (
                    not state.get("connected")
                    or not state.get("planEnabled")
                    or not state.get("accountId")
                ):
                    raise ValueError("Conecte o ChatGPT e permita o uso do plano.")
                account_id = state["accountId"]
            if value["providerId"] == "chatgpt" and (
                before.provider_id != "chatgpt" or value["modelId"] != before.model_id
            ):
                request = self.profile_model_request(
                    value["id"], "chatgpt", value["customEndpoint"], context, revision
                )
                if (
                    model_catalog is None
                    or request.status != "idle"
                    or model_catalog[0] != request.request_key
                    or value["modelId"] not in model_catalog[1]
                ):
                    raise ValueError(
                        "Escolha um modelo do catálogo deste perfil e desta conta."
                    )
                changed_route["request"] = request
            route = validate_workflow_route(
                replace(
                    before,
                    provider_id=value["providerId"],
                    model_id=value["modelId"],
                    custom_endpoint=value["customEndpoint"],
                    enabled=value["enabled"],
                    account_id=account_id,
                ),
                "rewrite",
            )
            changed_route["scope"], changed_route["route"] = profile.source_scope, route
            profiles = tuple(
                replace(p, route=route) if p.id == profile.id else p
                for p in settings.profiles
            )
            return replace(settings, profiles=profiles), actions

        def change_config(config):
            return (
                replace(
                    config,
                    workflows=config.workflows.with_route(
                        changed_route["scope"], changed_route["route"]
                    ),
                )
                if changed_route["scope"]
                else config
            )

        def validate_model():
            request = changed_route.get("request")
            if request is not None:
                current = self.profile_model_request(
                    value["id"],
                    value["providerId"],
                    value["customEndpoint"],
                    context,
                    revision,
                )
                if current != request:
                    raise TextActionStateChanged(
                        "O catálogo mudou. Atualize os modelos do perfil."
                    )

        return self._transaction(
            mutate,
            context,
            revision,
            config_change=change_config,
            precommit=validate_model,
        )

    @staticmethod
    def profile_name(profile_id):
        return {
            "default": "Text service",
            "legacy-rewrite": "Rewrite",
            "legacy-translation": "Translation",
        }.get(profile_id, profile_id)

    def profile_available(self, route, config):
        if not route.enabled or not route.model_id:
            return False
        if route.provider_id == "chatgpt":
            try:
                state = (
                    self.chatgpt_session.snapshot()
                    if self.chatgpt_session is not None
                    else {}
                )
                return bool(
                    state.get("connected")
                    and state.get("planEnabled")
                    and route.account_id
                    and state.get("accountId") == route.account_id
                )
            except Exception:
                return False
        return bool(getattr(config, route.provider_id).api_key)

    def set_after(self, action_id, language, context, revision):
        from text_actions import TEXT_LANGUAGES

        if (
            type(action_id) is not str
            or type(language) is not str
            or language not in TEXT_LANGUAGES
        ):
            raise ValueError("Invalid post-dictation action")

        def mutate(settings, actions):
            action = next((a for a in actions if a.id == action_id and a.enabled), None)
            if action_id and action is None:
                raise ValueError("Unknown or disabled text action")
            if (
                action is not None
                and action.kind == "translation"
                and language == "auto"
            ):
                raise ValueError("Select a translation language")
            after = {
                key: dict(value) for key, value in settings.after_dictation.items()
            }
            after.setdefault(self._device_key(), {})[
                self.dictation_context(self.repository.load())
            ] = {"id": action_id, "language": language}
            return replace(settings, after_dictation=after), actions

        return self._transaction(mutate, context, revision)

    def resolve(self, action_id):
        account_guard = getattr(self.account, "_lock", None) or nullcontext()
        config_guard = getattr(self.repository, "_lock", None) or nullcontext()
        with self._lock, account_guard, config_guard:
            actions = self._library()[1]
            action = next((a for a in actions if a.id == action_id), None)
            if action is None:
                raise AccountError(
                    "A ação não existe. Atualize as ações.", code="text_action_missing"
                )
            if not action.enabled:
                raise AccountError(
                    "A ação está desativada.", code="text_action_disabled"
                )
            config = self.repository.load()
            route = (
                None
                if self.managed()
                else settings_for(config)
                .profile(action.processing_profile_id)
                .resolved(config)
            )
            if route is not None and not route.enabled:
                raise ValueError("Text processing profile is disabled")
            return TextActionSnapshot(
                action,
                route,
                account_context=self.owner(),
                operation_id=str(uuid.uuid4()),
                context=self.context(),
                config=config,
            )

    def resolve_after_dictation(self):
        account_guard = getattr(self.account, "_lock", None) or nullcontext()
        config_guard = getattr(self.repository, "_lock", None) or nullcontext()
        with self._lock, account_guard, config_guard:
            # Account identity remains mandatory even when optional AI is off.
            owner, context = self.owner(), self.context()
            config = self.repository.load()
            policy = DictationCleanupPolicy(
                cleanup_level(config.dictation_cleanup_level)
            )
            local = config.workflow("transcription").provider_id == "local_asr"
            scope = "local_asr_refinement" if local else "refinement"
            permitted = self.managed() or (
                config.workflow(scope).enabled
                and (not local or config.local_asr_cloud_refinement)
            )
            if not policy.allows_refinement(permitted):
                return DictationTextActionSnapshot(None, "auto", context, owner, config)
            after = (
                settings_for(config)
                .after_dictation.get(self._device_key(), {})
                .get(self.dictation_context(config), {})
            )
            action_id = after.get("id", "")
            action, error = None, ""
            if action_id:
                try:
                    action = self.resolve(action_id)
                except (AccountError, ValueError) as problem:
                    error = type(problem).__name__
            return DictationTextActionSnapshot(
                action,
                after.get("language", "auto"),
                context,
                owner,
                config,
                error,
            )

    def is_current(self, snapshot):
        try:
            return (
                snapshot.context == self.context()
                and snapshot.account_context == self.owner()
            )
        except AccountError:
            return False
