"""Optional account, hosted dictation and revision-safe vocabulary sync.

No Qt, microphone, environment/profile lookup or network work at import time.
Provider keys and guest history never enter this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import threading
import time
from typing import Any
from urllib.parse import urlsplit
import uuid

import requests

from dictionary_snippets import (
    DictionaryEntry,
    DictionarySnippets,
    LocalDictionarySnippetsRepository,
    _atomic_write_json,
)
from provider_types import TranscriptionResult
from secret_store import SecretStore, create_secret_store
from shared.localization import device_language

SECRET_ID = "clarify_account"


class AccountError(RuntimeError):
    def __init__(self, message, *, code="", phase="", operation_id="", status=None):
        super().__init__(message)
        self.code = code
        self.phase = phase
        self.operation_id = operation_id
        self.status = status


def _processing_error(status, result, *, text=False):
    """Use bounded service codes, never provider bodies or arbitrary server copy."""
    unavailable = "O processamento do Clarify está indisponível no momento."
    invalid_audio = "Grave um áudio válido de até 5 minutos."
    invalid_text = "Selecione um texto válido para processar."
    busy = "Já existe um processamento em andamento."
    replay = (
        "Esta solicitação não pode ser repetida. Inicie uma nova ação."
        if text
        else "Esta solicitação já foi processada. Inicie uma nova gravação."
    )
    failure = (
        "Não foi possível processar o texto. Tente novamente."
        if text
        else "Não foi possível transcrever o áudio. Tente novamente."
    )
    messages = {
        "no_speech": "Nenhuma fala foi reconhecida. Tente falar novamente.",
        "transcription_failed": "Não foi possível transcrever o áudio. Tente novamente.",
        "text_processing_failed": "Não foi possível processar o texto. Tente novamente.",
        "processing_failed": "Não foi possível concluir o processamento. Tente novamente.",
        "authentication_required": "Entre na conta novamente.",
        "allowance_exhausted": "Sua cota foi atingida.",
        "rate_limited": "Muitas solicitações. Aguarde um momento.",
        "account_busy": busy,
        "service_busy": "O Clarify está ocupado. Aguarde um momento.",
        "hosted_unavailable": unavailable,
        "service_budget_exhausted": unavailable,
        "invalid_audio": invalid_audio,
        "invalid_duration": invalid_audio,
        "invalid_audio_request": invalid_audio,
        "invalid_text_request": invalid_text,
        "invalid_request": invalid_text if text else invalid_audio,
        "operation_conflict": replay,
        "operation_expired": replay,
        "operation_pending": busy,
    }
    code = result.get("code")
    code = code if isinstance(code, str) and code in messages else ""
    # Session invalidation in _request takes precedence over an inconsistent body.
    if status in {401, 403}:
        code = "authentication_required"
    message = messages.get(code) or {
        400: invalid_text if text else invalid_audio,
        409: busy,
        410: replay,
        429: "Sua cota ou o limite de solicitações foi atingido. Aguarde ou use sua própria chave.",
        503: unavailable,
    }.get(status, failure)
    phase = result.get("phase")
    if not isinstance(phase, str) or phase not in {
        "validation",
        "admission",
        "transcription",
        "text",
        "processing",
    }:
        phase = ""
    operation_id = result.get("operation_id")
    try:
        if not isinstance(operation_id, str) or len(operation_id) != 36:
            raise ValueError()
        operation_id = str(uuid.UUID(operation_id))
    except ValueError:
        operation_id = ""
    return AccountError(
        message, code=code, phase=phase, operation_id=operation_id, status=status
    )


class DictionaryConflict(AccountError):
    pass


@dataclass(frozen=True)
class HistoryIdentity:
    endpoint: str
    user_id: str
    generation: int


def endpoint(value: str) -> str:
    value = value.strip().rstrip("/")
    if not value:
        return ""
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        and not (
            parsed.scheme == "http"
            and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        )
    ) or (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path
    ):
        raise AccountError("Use um endereço HTTPS, sem caminho, usuário ou senha.")
    return value


def merge_dictionary(base, local, remote, *, prefer=None):
    """Three-way merge. Concurrent changes to the same term require a decision."""

    def index(values):
        document = DictionarySnippets(
            tuple(DictionaryEntry.from_mapping(item) for item in values)
        )
        return {
            entry.term.casefold(): entry.to_mapping() for entry in document.dictionary
        }

    before, ours, theirs = index(base), index(local), index(remote)
    merged = []
    for key in dict.fromkeys([*theirs, *ours, *before]):
        b, a, c = before.get(key), ours.get(key), theirs.get(key)
        if a == b:
            chosen = c
        elif c == b or a == c:
            chosen = a
        elif prefer == "local":
            chosen = a
        elif prefer == "remote":
            chosen = c
        else:
            raise DictionaryConflict(
                "A mesma palavra mudou nos dois dispositivos. As cópias foram preservadas. Escolha qual versão manter nas palavras em conflito."
            )
        if chosen is not None:
            merged.append(chosen)
    # Enforce the joint limit after merging two individually valid documents.
    return [
        entry.to_mapping()
        for entry in DictionarySnippets(
            tuple(DictionaryEntry.from_mapping(item) for item in merged)
        ).dictionary
    ]


class AccountService:
    def __init__(
        self,
        directory,
        *,
        secrets: SecretStore | None = None,
        request=None,
        default_endpoint="",
        ui_language=None,
        clock=time.monotonic,
    ):
        self.directory = Path(directory)
        self.path = self.directory / "account.json"
        self.secrets = secrets or create_secret_store(
            self.directory, filename_stem="account-secrets"
        )
        self.request = request or requests.request
        self.ui_language = ui_language or device_language()
        self._clock = clock
        self._last_refresh_attempt = float("-inf")
        self._last_sync_attempt = float("-inf")
        self.default_endpoint = endpoint(default_endpoint)
        self._lock = threading.RLock()
        self._generation = 0
        self._ending_session = False
        self._busy = False
        self._state = self._read(self.path, {})
        self._usage: dict[str, Any] = {}
        self._usage_generation = 0
        self._dictionary_conflict = False
        self._sync_error = ""
        self.history = None
        try:
            endpoint(self._state.get("endpoint", self.default_endpoint))
            if self._state.get("user_id"):
                uuid.UUID(self._state["user_id"])
                # Existing signed-in profiles use account processing immediately.
                # Keep the marker after expiry so personal keys are not used.
                self._state["mode"] = "hosted"
        except (TypeError, ValueError, AccountError):
            self._state = {}

    @staticmethod
    def _read(path, default):
        try:
            result = json.loads(Path(path).read_text(encoding="utf-8"))
            return result if isinstance(result, dict) else default
        except (OSError, ValueError):
            return default

    def _save(self):
        _atomic_write_json(self.path, self._state)

    @property
    def busy(self):
        with self._lock:
            return self._busy

    def begin_change(self):
        with self._lock:
            if self._busy:
                return False
            self._busy = True
            return True

    def end_change(self):
        with self._lock:
            self._busy = False

    @property
    def signed_in(self):
        with self._lock:
            return bool(self._state.get("user_id"))

    @property
    def hosted(self):
        with self._lock:
            return bool(self._state.get("user_id"))

    @property
    def managed(self):
        """An expired managed session cannot silently fall back to personal keys."""
        with self._lock:
            return (
                bool(self._state.get("user_id")) or self._state.get("mode") == "hosted"
            )

    @property
    def scope(self):
        with self._lock:
            value = self._state.get("user_id")
            return str(uuid.UUID(value)) if value else None

    def snapshot(self):
        with self._lock:
            return {
                "endpoint": self._state.get("endpoint", self.default_endpoint),
                "signedIn": bool(self._state.get("user_id")),
                "managed": self.managed,
                "email": self._state.get("email", ""),
                "pending": self._state.get("pending", ""),
                "hosted": self.hosted,
                "syncEnabled": bool(self._state.get("sync")),
                "usage": dict(self._usage),
                "dictionaryConflict": self._dictionary_conflict,
                "syncError": self._sync_error,
            }

    def configure(self, value):
        with self._lock:
            if self._state.get("user_id"):
                raise AccountError("Saia da conta antes de alterar o servidor.")
            self.secrets.delete(SECRET_ID)
            self._state = {"endpoint": endpoint(value)}
            self._generation += 1
            self._save()

    def history_identity(self):
        """Capture the account/session before starting a history operation."""
        with self._lock:
            user_id = self.scope
            if not user_id or self._ending_session:
                return None
            return HistoryIdentity(
                endpoint(self._state.get("endpoint", self.default_endpoint)),
                user_id,
                self._generation,
            )

    def _request(
        self,
        method,
        path,
        *,
        cancel=None,
        expected_identity=None,
        ending_session=False,
        **kwargs,
    ):
        with self._lock:
            if self._ending_session and not ending_session:
                raise AccountError("A conta mudou. O resultado foi descartado.")
            if (
                expected_identity is not None
                and expected_identity != self.history_identity()
            ):
                raise AccountError("A conta mudou. O resultado foi descartado.")
            base = self._state.get("endpoint", self.default_endpoint)
            generation = self._generation
            usage_generation = self._usage_generation
            token = self.secrets.get(SECRET_ID)
        if not base:
            raise AccountError(
                "O serviço Clarify ainda não foi configurado nesta versão."
            )
        if cancel:
            cancel.raise_if_cancelled()
        headers = {"Accept": "application/json", "Accept-Language": self.ui_language}
        if token:
            headers["X-Session-Token"] = token
        try:
            response = self.request(
                method,
                endpoint(base) + path,
                headers=headers,
                timeout=(5, 100 if path in {"/v1/dictations", "/v1/text"} else 15),
                allow_redirects=False,
                **kwargs,
            )
            processing_failure = (
                path in {"/v1/dictations", "/v1/text"} and response.status_code != 200
            )
            try:
                result = response.json() if response.content else {}
            except ValueError:
                if not processing_failure:
                    raise
                result = {}
            if not isinstance(result, dict):
                if not processing_failure:
                    raise ValueError()
                result = {}
        except (requests.RequestException, ValueError):
            raise AccountError(
                "Não foi possível acessar o Clarify. Verifique a conexão."
            ) from None
        with self._lock:
            if generation != self._generation:
                raise AccountError("A conta mudou. O resultado foi descartado.")
            if response.status_code in {401, 403} and path.startswith("/v1/"):
                self.secrets.delete(SECRET_ID)
                self._state.pop("user_id", None)
                self._state["sync"] = False
                self._usage = {}
                self._usage_generation += 1
                self._generation += 1
                self._save()
            else:
                meta = result.get("meta")
                new_token = (
                    meta.get("session_token") if isinstance(meta, dict) else None
                )
                if isinstance(new_token, str) and new_token:
                    self.secrets.set(SECRET_ID, new_token)
                if isinstance(result.get("usage"), dict) and (
                    method == "POST" or usage_generation == self._usage_generation
                ):
                    self._usage = result["usage"]
                    self._usage_generation += 1
        if cancel:
            cancel.raise_if_cancelled()
        return response.status_code, result

    def authenticate(self, action, value):
        if action in {"login", "signup"}:
            if self.snapshot()["signedIn"]:
                raise AccountError("Saia da conta atual primeiro.")
            path = "/auth/signup" if action == "signup" else "/auth/continue"
            code, result = self._request(
                "POST", "/_allauth/app/v1" + path, json={"email": value.strip()}
            )
            if code not in {200, 401}:
                raise AccountError(
                    "Não foi possível enviar o código. Confira o e-mail ou aguarde antes de tentar novamente."
                )
            with self._lock:
                self._state.update(pending=action, email=value.strip())
                self._save()
        elif action == "confirm":
            pending = self._state.get("pending")
            if pending not in {"login", "signup"}:
                raise AccountError("Solicite um novo código.")
            path = "/auth/email/verify" if pending == "signup" else "/auth/code/confirm"
            payload = {"key" if pending == "signup" else "code": value.strip()}
            code, result = self._request(
                "POST", "/_allauth/app/v1" + path, json=payload
            )
            if code != 200 or not result.get("meta", {}).get("is_authenticated"):
                raise AccountError(
                    "O código é inválido ou expirou. Solicite um novo código."
                )
            self.refresh()
        else:
            raise AccountError("Ação de conta inválida.")

    def refresh(self):
        self._last_refresh_attempt = self._clock()
        with self._lock:
            generation = self._generation
        code, result = self._request("GET", "/v1/account")
        if code != 200:
            raise AccountError("A sessão expirou. Entre na conta novamente.")
        user_id = str(uuid.UUID(result["id"]))
        with self._lock:
            if generation != self._generation:
                raise AccountError("A conta mudou. O resultado foi descartado.")
            if self._state.get("user_id") != user_id:
                self._generation += 1
            self._state.update(
                user_id=user_id, email=result["email"], pending="", mode="hosted"
            )
            self._save()

    def refresh_if_due(self, service, *, force=False):
        """Foreground refresh, at most once a minute, including after failures."""
        if not self.signed_in:
            return
        if self._clock() - self._last_refresh_attempt >= 60:
            self.refresh()
        if (
            self.signed_in
            and not self._dictionary_conflict
            and (force or self._clock() - self._last_sync_attempt >= 60)
        ):
            try:
                self.sync_dictionary(service)
            except AccountError as error:
                with self._lock:
                    self._sync_error = str(error)
        if self.history is not None:
            self.history.sync_safely(force=force)

    def logout(self, *, delete=False):
        with self._lock:
            history_owner = self.history_identity()
            scope = self._state.get("user_id")
            self._generation += 1
            self._ending_session = True
        try:
            if delete:
                code, _ = self._request(
                    "DELETE", "/v1/account", json={"confirm": True}, ending_session=True
                )
                if code != 204:
                    raise AccountError(
                        "Não foi possível excluir a conta. Finalize o ditado e tente novamente."
                    )
            else:
                self._request(
                    "DELETE", "/_allauth/app/v1/auth/session", ending_session=True
                )
        except AccountError:
            if delete:
                raise
        finally:
            with self._lock:
                self._ending_session = False
        with self._lock:
            self.secrets.delete(SECRET_ID)
            self._state = {
                "endpoint": self._state.get("endpoint", self.default_endpoint)
            }
            self._usage = {}
            self._dictionary_conflict = False
            self._sync_error = ""
            self._generation += 1
            self._save()
        if delete and scope:
            if self.history is not None:
                self.history.remove_account(history_owner)
            target = self.directory / "account-data" / str(uuid.UUID(scope))
            # Remove only this account's cache, never the local profile.
            for name in ("dictionary.json", "sync.json"):
                (target / name).unlink(missing_ok=True)

    def sync_dictionary(self, service, *, prefer=None):
        self._last_sync_attempt = self._clock()
        with self._lock:
            user_id = self._state.get("user_id")
            if not user_id:
                raise AccountError("Entre na sua conta primeiro.")
            target = self.directory / "account-data" / str(uuid.UUID(user_id))
            metadata = self._read(target / "sync.json", {})
            # Resume this account's cache. First connection imports local words;
            # snippets remain on the device and guest data is never overwritten.
            cached = LocalDictionarySnippetsRepository(
                target / "dictionary.json"
            ).load()
            local = cached.dictionary if metadata else service.state.dictionary
            base = metadata.get("base", [])
            generation = self._generation
        code, remote = self._request("GET", "/v1/dictionary")
        if code != 200:
            raise AccountError("Não foi possível carregar o dicionário da conta.")
        local_entries = [e.to_mapping() for e in local]
        try:
            entries = merge_dictionary(
                base, local_entries, remote["entries"], prefer=prefer
            )
        except DictionaryConflict:
            with self._lock:
                self._dictionary_conflict = True
            raise
        if entries != remote["entries"]:
            code, remote = self._request(
                "PUT",
                "/v1/dictionary",
                json={"revision": remote["revision"], "entries": entries},
            )
            if code != 200:
                raise AccountError(
                    "O dicionário mudou em outro dispositivo. As cópias foram preservadas. Sincronize novamente."
                )
        with self._lock:
            if generation != self._generation or self._state.get("user_id") != user_id:
                raise AccountError("A conta mudou. Sincronize novamente.")
            current = (
                LocalDictionarySnippetsRepository(target / "dictionary.json")
                .load()
                .dictionary
                if metadata
                else service.state.dictionary
            )
            if current != local:
                if metadata:
                    _atomic_write_json(
                        target / "sync.json",
                        {"base": remote["entries"], "revision": remote["revision"]},
                    )
                raise AccountError(
                    "As palavras mudaram durante a sincronização. As alterações locais foram mantidas. Sincronize novamente."
                )
            LocalDictionarySnippetsRepository(target / "dictionary.json").save(
                DictionarySnippets(
                    tuple(DictionaryEntry.from_mapping(e) for e in remote["entries"])
                )
            )
            _atomic_write_json(
                target / "sync.json",
                {"base": remote["entries"], "revision": remote["revision"]},
            )
            self._state["sync"] = True
            self._dictionary_conflict = False
            self._sync_error = ""
            self._save()
            service.reload()

    def transcribe(self, source, language, dictionary_service):
        if not self.hosted:
            raise AccountError("Entre na conta novamente.")
        if source.cancel_token:
            source.cancel_token.raise_if_cancelled()
        if self.scope and self._clock() - self._last_sync_attempt >= 60:
            try:
                self.sync_dictionary(dictionary_service)
            except AccountError as error:
                with self._lock:
                    self._sync_error = str(error)
        data = source.audio_bytes or source.audio_path.read_bytes()
        code, result = self._request(
            "POST",
            "/v1/dictations",
            cancel=source.cancel_token,
            data={
                "operation_id": str(uuid.uuid4()),
                "language": str(language or "auto").split("-")[0],
            },
            files={"audio": ("clip.wav", data, "audio/wav")},
        )
        if code != 200:
            if code in {401, 403}:
                dictionary_service.reload()
            raise _processing_error(code, result)
        raw, text = result.get("transcript"), result.get("text")
        if not isinstance(raw, str) or not isinstance(text, str) or not text.strip():
            raise AccountError("O Clarify retornou um resultado inválido.")
        rewritten = result.get("rewritten") is True
        return TranscriptionResult(
            dictionary_service.expand(text) if rewritten else raw,
            "clarify",
            "whisper-large-v3-turbo",
            raw_text=raw,
            refined_text=text if rewritten else None,
            refinement_failed=not rewritten,
            refinement_provider_id="clarify",
            refinement_model="openai/gpt-oss-20b",
        )

    def transform_text(self, text, action, language="auto", *, cancel=None):
        if not self.hosted:
            raise AccountError("Entre na conta novamente.")
        code, result = self._request(
            "POST",
            "/v1/text",
            cancel=cancel,
            json={
                "operation_id": str(uuid.uuid4()),
                "action": action,
                "text": str(text),
                "language": str(language or "auto").split("-")[0],
            },
        )
        if code != 200:
            raise _processing_error(code, result, text=True)
        value = result.get("text")
        if not isinstance(value, str) or not value.strip():
            raise AccountError("O Clarify retornou um resultado inválido.")
        return value


class AccountDictionaryRepository:
    """Scope vocabulary per account; snippets always remain in the local profile."""

    def __init__(self, account, local):
        self.account, self.local = account, local

    @property
    def path(self):
        scope = self.account.scope
        return (
            self.account.directory / "account-data" / scope / "dictionary.json"
            if scope
            else self.local.path
        )

    def load(self):
        original = self.local.load()
        if not self.account.scope:
            return original
        if not self.path.exists():
            # Seed a separate cache once. Offline account edits never modify BYOK words.
            LocalDictionarySnippetsRepository(self.path).save(
                replace(original, snippets=())
            )
            _atomic_write_json(
                self.path.with_name("sync.json"), {"base": [], "revision": -1}
            )
        cached = LocalDictionarySnippetsRepository(self.path).load()
        return replace(original, dictionary=cached.dictionary)

    def save(self, state):
        if not self.account.scope:
            return self.local.save(state)
        self.local.save(replace(self.local.load(), snippets=state.snippets))
        return LocalDictionarySnippetsRepository(self.path).save(
            replace(state, snippets=())
        )
