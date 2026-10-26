"""ChatGPT OAuth and protected, profile-scoped plan sessions.

This boundary owns authorization, identity validation and rotating tokens.
It never sends inference requests. Construction and import have no file effects.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
import copy
from dataclasses import dataclass, field
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import uuid

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import requests

from secret_store import create_secret_store


ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
AUTHORIZE_ENDPOINT = ISSUER + "/api/accounts/authorize"
TOKEN_ENDPOINT = ISSUER + "/api/accounts/oauth/token"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPES = frozenset(("resource.invoke", "chatgpt.tokens.use.direct"))
_MAX_RESPONSE = 256 * 1024
_TERMINAL_REFRESH_CODES = frozenset(
    (
        "invalid_grant",
        "invalid_refresh_token",
        "token_expired",
        "refresh_token_expired",
        "refresh_token_invalidated",
        "refresh_token_reused",
    )
)
_OAUTH_ERROR_CODES = _TERMINAL_REFRESH_CODES | {"invalid_client"}
_MESSAGES = {
    "cancelled": "ChatGPT sign-in or access was cancelled.",
    "stale_session": "The selected ChatGPT session changed. Start the action again.",
    "timeout": "ChatGPT sign-in timed out. Start sign-in again.",
    "browser_failed": "The browser could not open. Start sign-in again.",
    "callback_invalid": "The ChatGPT callback is invalid. Start sign-in again.",
    "access_denied": "ChatGPT permission was declined. Start sign-in to enable it.",
    "authorization_failed": "ChatGPT authorization failed. Start sign-in again.",
    "invalid_response": "ChatGPT returned an invalid authentication response.",
    "identity_invalid": "The ChatGPT identity could not be verified. Sign in again.",
    "registration_mismatch": "The ChatGPT registration changed. Select the saved account.",
    "network": "Could not reach ChatGPT. Check the connection and try again.",
    "storage_unavailable": "ChatGPT credentials could not be saved. Check profile access.",
    "storage_invalid": "The saved ChatGPT record is invalid. Restore the profile backup.",
    "sign_in_required": "Sign in to the selected ChatGPT account.",
    "plan_disabled": "Enable ChatGPT plan use for the selected account.",
    "unknown_account": "Select a saved ChatGPT account.",
    "refresh_failed": "ChatGPT access could not be renewed. Sign in again.",
    "revocation_failed": "Signed out locally. Disconnect Clarify in ChatGPT Settings to end remote access.",
}


class ChatGPTPlanError(RuntimeError):
    """A machine code and safe text, without remote response material."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


def _error(code):
    return ChatGPTPlanError(_MESSAGES[code], code=code)


class _OAuthResponseError(ChatGPTPlanError):
    def __init__(self, oauth_code=""):
        super().__init__(_MESSAGES["authorization_failed"], code="authorization_failed")
        self.oauth_code = oauth_code if oauth_code in _OAUTH_ERROR_CODES else ""


@dataclass(frozen=True)
class ChatGPTCredential:
    access_token: str = field(repr=False)
    generation: int
    account_id: str


def _cancelled(token):
    if token is None:
        return False
    if callable(token):
        return bool(token())
    if hasattr(token, "is_set"):
        return token.is_set()
    value = getattr(token, "cancelled", False)
    return bool(value() if callable(value) else value)


def _check_cancel(token):
    if _cancelled(token):
        raise _error("cancelled")


def _close(resource):
    if resource is not None:
        try:
            resource.close()
        except Exception:
            # Cleanup must not expose transport or browser diagnostics.
            pass


def _text(value, limit=16384):
    return (
        isinstance(value, str)
        and 0 < len(value) <= limit
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)
    )


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _json(value):
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError()
            result[key] = item
        return result

    return json.loads(value, object_pairs_hook=pairs)


def _b64decode(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError()
    return base64.b64decode(
        value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
    )


def _b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _account_id(subject, client_id):
    return hashlib.sha256(json.dumps([ISSUER, subject, client_id]).encode()).hexdigest()


def _endpoint(value):
    if not isinstance(value, str):
        raise _error("invalid_response")
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise _error("invalid_response") from None
    if (parsed.scheme, parsed.netloc) != ("https", "auth.openai.com") or (
        parsed.query or parsed.fragment or not parsed.path.startswith("/")
    ):
        raise _error("invalid_response")
    return value


def _callback(url, redirect_uri, state, saved_client):
    try:
        if not isinstance(url, str) or len(url) > 16384:
            raise ValueError()
        parsed, expected = urlsplit(url), urlsplit(redirect_uri)
        if (parsed.scheme, parsed.netloc, parsed.path) != (
            expected.scheme,
            expected.netloc,
            "/auth/callback",
        ) or parsed.fragment:
            raise ValueError()
        query = parse_qs(
            parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=20
        )
        if any(len(values) != 1 for values in query.values()):
            raise ValueError()
        if not secrets.compare_digest(query.get("state", [""])[0], state):
            raise ValueError()
        if "error" in query:
            if "code" in query or not _text(query["error"][0], 128):
                raise ValueError()
            raise _error(
                "access_denied"
                if query["error"][0] == "access_denied"
                else "authorization_failed"
            )
        code = query.get("code", [""])[0]
        client = query.get("client_id", [saved_client or ""])[0]
        if (
            not _text(code)
            or not _text(client, 1024)
            or client == "dynamic_agent_client"
        ):
            raise ValueError()
        if saved_client and client != saved_client:
            raise _error("registration_mismatch")
        return code, client
    except (ValueError, TypeError, UnicodeError):
        raise _error("callback_invalid") from None


class _LoopbackListener:
    """Bound IPv4 loopback listener with no logs or callback echoes."""

    def __init__(self):
        self._result = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        listener = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def send_error(self, code, message=None, explain=None):
                # The base implementation can echo the raw request line.
                self.send_response(code)
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()

            def do_GET(self):
                host = self.headers.get_all("Host", [])
                parsed = urlsplit(self.path)
                valid = (
                    len(self.path) <= 16384
                    and parsed.path == "/auth/callback"
                    and not parsed.scheme
                    and not parsed.netloc
                    and host == [urlsplit(listener.redirect_uri).netloc]
                    and self.client_address[0] == "127.0.0.1"
                )
                if valid:
                    with listener._lock:
                        if listener._result is None:
                            listener._result = "http://" + host[0] + self.path
                            listener._ready.set()
                body = (
                    b"Return to Clarify to complete sign-in."
                    if valid
                    else b"Invalid callback."
                )
                self.send_response(200 if valid else 400)
                for name, value in {
                    "Content-Type": "text/plain; charset=utf-8",
                    "Content-Length": str(len(body)),
                    "Cache-Control": "no-store",
                    "Referrer-Policy": "no-referrer",
                    "Content-Security-Policy": "default-src 'none'",
                }.items():
                    self.send_header(name, value)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

        class Server(ThreadingHTTPServer):
            daemon_threads = True

            def get_request(self):
                sock, address = super().get_request()
                sock.settimeout(1.0)
                return sock, address

            def handle_error(self, *_args):
                pass

        self._server = Server(("127.0.0.1", 0), Handler)
        self.redirect_uri = f"http://127.0.0.1:{self._server.server_port}/auth/callback"
        self._thread = threading.Thread(
            target=lambda: self._server.serve_forever(poll_interval=0.05), daemon=True
        )
        self._thread.start()

    def wait(self, *, check):
        while not self._ready.wait(0.05):
            check()
        check()
        return self._result

    def close(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)


@contextmanager
def _profile_guard(directory, check):
    """Serialize short record transactions across processes, outside HTTP.

    The Unix lock file contains no data. Windows uses a named mutex. A durable
    refresh claim prevents replay after an uncertain send or a process crash.
    """
    deadline, handle, stream, locked = time.monotonic() + 5, None, None, False
    try:
        if os.name == "nt":
            import ctypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateMutexW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_bool,
                ctypes.c_wchar_p,
            ]
            kernel.CreateMutexW.restype = ctypes.c_void_p
            kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            kernel.WaitForSingleObject.restype = ctypes.c_uint32
            kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            name = hashlib.sha256(os.path.normcase(str(directory)).encode()).hexdigest()
            handle = kernel.CreateMutexW(None, False, "Local\\ClarifyChatGPT-" + name)
            if not handle:
                raise OSError()
        else:
            import fcntl

            directory.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(
                directory / ".chatgpt-session.lock", os.O_CREAT | os.O_RDWR, 0o600
            )
            stream = os.fdopen(descriptor, "rb")
        while not locked:
            check()
            if time.monotonic() >= deadline:
                raise OSError()
            if os.name == "nt":
                result = kernel.WaitForSingleObject(handle, 50)
                if result in (0, 128):
                    locked = True
                elif result != 258:
                    raise OSError()
            else:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                except BlockingIOError:
                    time.sleep(0.05)
        yield
    except OSError:
        raise _error("storage_unavailable") from None
    finally:
        if handle:
            if locked:
                kernel.ReleaseMutex(handle)
            kernel.CloseHandle(handle)
        if stream:
            stream.close()


class ChatGPTPlanSession:
    def __init__(
        self,
        data_directory: Path,
        *,
        secret_store=None,
        http=None,
        clock=time.time,
        monotonic=time.monotonic,
        listener_factory=_LoopbackListener,
        auth_timeout=180.0,
    ):
        self.data_directory = Path(data_directory).resolve()
        self._store = (
            secret_store
            if secret_store is not None
            else create_secret_store(
                self.data_directory, filename_stem="chatgpt-secrets"
            )
        )
        self._http = http
        self._clock, self._monotonic = clock, monotonic
        self._listener_factory = listener_factory
        self._auth_timeout = min(max(float(auth_timeout), 0.1), 300.0)
        self._lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._data = None
        self._file_signature = None
        self._generation = 0
        self._attempt = None
        self._local_signouts = set()

    def _invalidate_locked(self):
        self._generation += 1
        if self._attempt is not None:
            self._attempt.set()

    def _load_locked(self):
        try:
            signature = self._store_signature()
            if (
                self._data is not None
                and signature is not None
                and signature == self._file_signature
            ):
                return
            raw = self._store.get("chatgpt")
            data = (
                _json(raw)
                if raw is not None
                else {
                    "version": 1,
                    "ext_agent_host_id": "",
                    "active": "",
                    "accounts": {},
                }
            )
            if (
                not isinstance(data, dict)
                or type(data.get("version")) is not int
                or data["version"] != 1
            ):
                raise ValueError()
            accounts = data["accounts"]
            if not isinstance(accounts, dict) or len(accounts) > 100:
                raise ValueError()
            if not isinstance(data["ext_agent_host_id"], str) or not isinstance(
                data["active"], str
            ):
                raise ValueError()
            pending = data.get("pending_client_id", "")
            if not isinstance(pending, str) or (
                pending
                and (not _text(pending, 1024) or pending == "dynamic_agent_client")
            ):
                raise ValueError()
            if (accounts or pending or data["ext_agent_host_id"]) and not _text(
                data["ext_agent_host_id"], 1024
            ):
                raise ValueError()
            if data["active"] and data["active"] not in accounts:
                raise ValueError()
            for key, record in accounts.items():
                if not isinstance(record, dict) or record.get("issuer") != ISSUER:
                    raise ValueError()
                if not _text(record.get("subject"), 1024) or not _text(
                    record.get("client_id"), 1024
                ):
                    raise ValueError()
                if record["client_id"] == "dynamic_agent_client" or key != _account_id(
                    record["subject"], record["client_id"]
                ):
                    raise ValueError()
                if not isinstance(record.get("email"), str) or not isinstance(
                    record.get("tokens"), dict
                ):
                    raise ValueError()
                if record["email"] and not _text(record["email"], 320):
                    raise ValueError()
                if type(record.get("plan_notice_seen", False)) is not bool:
                    raise ValueError()
                tokens = record["tokens"]
                if tokens and (
                    not _text(tokens.get("id_token"), 32768)
                    or not isinstance(tokens.get("scopes"), list)
                    or not all(_text(scope, 128) for scope in tokens["scopes"])
                    or not _number(tokens.get("expires_at"))
                    or not _number(tokens.get("earliest_refresh_at", 0))
                    or not all(
                        isinstance(tokens.get(name, ""), str)
                        for name in ("access_token", "refresh_token")
                    )
                    or (
                        PLAN_SCOPES.issubset(tokens["scopes"])
                        and not all(
                            _text(tokens.get(name))
                            for name in ("access_token", "refresh_token")
                        )
                    )
                ):
                    raise ValueError()
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise _error("storage_invalid") from None
        except Exception:
            raise _error("storage_unavailable") from None
        if self._data is not None and self._data != data:
            self._invalidate_locked()
        self._data = data
        # Use the pre-read signature. A replacement during the read then forces
        # another read on the next check, rather than hiding an external change.
        self._file_signature = signature

    def _store_signature(self):
        path = getattr(self._store, "path", None)
        if path is None:
            return None
        try:
            stat = Path(path).stat()
        except FileNotFoundError:
            return ("missing",)
        return (
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        )

    def _save_locked(self, data):
        try:
            # Persist transitions even when selection returns to the same
            # identity before another process observes the intermediate state.
            data["revision"] = secrets.token_urlsafe(24)
            self._store.set(
                "chatgpt", json.dumps(data, separators=(",", ":"), ensure_ascii=True)
            )
        except Exception:
            raise _error("storage_unavailable") from None
        self._data = data
        self._file_signature = None

    @contextmanager
    def _transaction(self, check=lambda: None):
        with self._lock, _profile_guard(self.data_directory, check):
            self._load_locked()
            check()
            yield

    def _selected_locked(self):
        return self._data["accounts"].get(self._data["active"])

    def _tokens_locked(self, record):
        if record is None or self._data["active"] in self._local_signouts:
            return {}
        return record["tokens"]

    def snapshot(self) -> dict:
        with self._lock:
            self._load_locked()
            record = self._selected_locked()
            tokens = self._tokens_locked(record)
            return {
                "connected": bool(tokens),
                "planEnabled": bool(tokens) and PLAN_SCOPES.issubset(tokens["scopes"]),
                "email": record["email"] if record else "",
                "accountId": self._data["active"],
                "accounts": [
                    {
                        "id": key,
                        "label": (value["email"] or "ChatGPT") + " (" + key[:12] + ")",
                    }
                    for key, value in self._data["accounts"].items()
                ],
                "generation": self._generation,
                "planNoticeSeen": bool(
                    record and record.get("plan_notice_seen", False)
                ),
            }

    def _request(self, method, url, *, data=None, check=lambda: None, empty=False):
        check()
        response = session = None
        deadline = self._monotonic() + 20
        try:
            transport = self._http
            if transport is None:
                session = requests.Session()
                session.trust_env = False
                transport = session
            response = transport.request(
                method,
                url,
                data=data,
                timeout=(3.05, 10.0),
                stream=True,
                allow_redirects=False,
                headers={"Accept": "application/json"},
            )
            check()
            content = bytearray()
            next_check = self._monotonic()
            # Yield on each byte so a slowly delivered response cannot keep a
            # larger buffered read alive past the total retrieval deadline.
            for chunk in response.iter_content(chunk_size=1):
                now = self._monotonic()
                if now > deadline:
                    raise _error("timeout")
                if now >= next_check:
                    check()
                    next_check = now + 0.05
                content.extend(chunk)
                if len(content) > _MAX_RESPONSE:
                    raise _error("invalid_response")
            if response.status_code != 200:
                code = ""
                if (
                    method == "POST"
                    and url == TOKEN_ENDPOINT
                    and response.status_code in {400, 401, 403}
                ):
                    try:
                        failure = _json(bytes(content))
                        value = (
                            failure.get("error") if isinstance(failure, dict) else None
                        )
                        if isinstance(value, dict):
                            value = value.get("code")
                        if isinstance(value, str) and value in _OAUTH_ERROR_CODES:
                            code = value
                    except (ValueError, TypeError, UnicodeError):
                        pass
                raise _OAuthResponseError(code)
            if empty and not content:
                return {}
            payload = _json(bytes(content))
            if not isinstance(payload, dict):
                raise ValueError()
            return payload
        except ChatGPTPlanError:
            raise
        except (ValueError, TypeError, UnicodeError):
            raise _error("invalid_response") from None
        except Exception:
            raise _error("network") from None
        finally:
            _close(response)
            _close(session)

    def _discovery(self, check=lambda: None):
        payload = self._request(
            "GET", ISSUER + "/.well-known/openid-configuration", check=check
        )
        if (
            payload.get("issuer") != ISSUER
            or payload.get("authorization_endpoint") != AUTHORIZE_ENDPOINT
            or payload.get("token_endpoint") != TOKEN_ENDPOINT
        ):
            raise _error("invalid_response")
        _endpoint(payload.get("jwks_uri"))
        if "revocation_endpoint" in payload:
            _endpoint(payload["revocation_endpoint"])
        algorithms = payload.get("id_token_signing_alg_values_supported")
        if not isinstance(algorithms, list) or "RS256" not in algorithms:
            raise _error("identity_invalid")
        return payload

    def _identity(self, token, client_id, nonce, discovery, check):
        try:
            if not _text(token, 32768):
                raise ValueError()
            header_part, claims_part, signature = token.split(".")
            header, claims = (
                _json(_b64decode(header_part)),
                _json(_b64decode(claims_part)),
            )
            if not isinstance(header, dict) or not isinstance(claims, dict):
                raise ValueError()
            if (
                header.get("alg") != "RS256"
                or not _text(header.get("kid"), 256)
                or any(name in header for name in ("crit", "jku", "x5u"))
            ):
                raise ValueError()
            jwks = self._request("GET", discovery["jwks_uri"], check=check)
            keys = jwks.get("keys")
            if (
                not isinstance(keys, list)
                or len(keys) > 32
                or not all(isinstance(key, dict) for key in keys)
            ):
                raise ValueError()
            matches = [key for key in keys if key.get("kid") == header["kid"]]
            if len(matches) != 1:
                raise ValueError()
            key = matches[0]
            if (
                key.get("kty") != "RSA"
                or key.get("use", "sig") != "sig"
                or key.get("alg", "RS256") != "RS256"
                or "verify" not in key.get("key_ops", ["verify"])
            ):
                raise ValueError()
            modulus, exponent = (
                int.from_bytes(_b64decode(key["n"]), "big"),
                int.from_bytes(_b64decode(key["e"]), "big"),
            )
            if not 2048 <= modulus.bit_length() <= 8192 or exponent != 65537:
                raise ValueError()
            rsa.RSAPublicNumbers(exponent, modulus).public_key().verify(
                _b64decode(signature),
                (header_part + "." + claims_part).encode("ascii"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            now, audience = self._clock(), claims.get("aud")
            valid_audience = audience == client_id or (
                isinstance(audience, list)
                and all(isinstance(item, str) for item in audience)
                and client_id in audience
                and (len(audience) == 1 or claims.get("azp") == client_id)
            )
            if (
                claims.get("iss") != ISSUER
                or not valid_audience
                or ("azp" in claims and claims["azp"] != client_id)
                or not _number(claims.get("exp"))
                or claims["exp"] <= now
                or not _text(claims.get("sub"), 1024)
            ):
                raise ValueError()
            for name in ("nbf", "iat"):
                if name in claims and (
                    not _number(claims[name]) or claims[name] > now + 30
                ):
                    raise ValueError()
            if nonce is not None and (
                not isinstance(claims.get("nonce"), str)
                or not secrets.compare_digest(claims["nonce"], nonce)
            ):
                raise ValueError()
            email = claims.get("email", "")
            if not isinstance(email, str) or (email and not _text(email, 320)):
                raise ValueError()
            check()
            return claims
        except ChatGPTPlanError:
            raise
        except Exception:
            raise _error("identity_invalid") from None

    def _token_set(self, payload, *, previous=None):
        scope = payload.get("scope")
        if "scope" not in payload and previous is not None:
            scopes = previous["scopes"]
        elif isinstance(scope, str) and len(scope) <= 4096:
            scopes = scope.split()
        else:
            raise _error("invalid_response")
        if not all(_text(item, 128) for item in scopes):
            raise _error("invalid_response")
        access, refresh = (
            payload.get("access_token", ""),
            payload.get("refresh_token", ""),
        )
        expires = payload.get("expires_in", 0)
        if not _number(expires) or not 0 <= expires <= 86400:
            raise _error("invalid_response")
        if not isinstance(access, str) or not isinstance(refresh, str):
            raise _error("invalid_response")
        if access and (
            not _text(access)
            or str(payload.get("token_type", "")).lower() != "bearer"
            or expires <= 0
        ):
            raise _error("invalid_response")
        if refresh and not _text(refresh):
            raise _error("invalid_response")
        if PLAN_SCOPES.issubset(scopes) and (not access or not refresh):
            raise _error("invalid_response")
        if previous is not None and (not access or not refresh):
            raise _error("invalid_response")
        earliest = payload.get("earliest_refresh_at", 0)
        if not _number(earliest) or earliest < 0:
            raise _error("invalid_response")
        return {
            "access_token": access,
            "refresh_token": refresh,
            "id_token": payload.get(
                "id_token", previous["id_token"] if previous else ""
            ),
            "scopes": list(dict.fromkeys(scopes)),
            "expires_at": self._clock() + expires,
            "earliest_refresh_at": earliest,
        }

    def sign_in(self, *, open_browser, cancel=None, new_account: bool = False) -> None:
        _check_cancel(cancel)
        attempt = threading.Event()
        with self._transaction(lambda: _check_cancel(cancel)):
            if self._attempt is not None:
                self._attempt.set()
            self._attempt = attempt
            data = copy.deepcopy(self._data)
            if not data["ext_agent_host_id"]:
                data["ext_agent_host_id"] = "urn:uuid:" + str(uuid.uuid4())
                self._save_locked(data)
            selected = None if new_account else copy.deepcopy(self._selected_locked())
            saved_client = (
                selected["client_id"] if selected else data.get("pending_client_id", "")
            )
            generation = self._generation
            host_id = data["ext_agent_host_id"]
        deadline = self._monotonic() + self._auth_timeout

        def check():
            _check_cancel(cancel)
            if attempt.is_set():
                raise _error("cancelled")
            if self._monotonic() >= deadline:
                raise _error("timeout")
            with self._lock:
                if self._generation != generation or self._attempt is not attempt:
                    raise _error("stale_session")

        listener = None
        try:
            discovery = self._discovery(check)
            check()
            listener = self._listener_factory()
            redirect = urlsplit(listener.redirect_uri)
            if (
                redirect.scheme != "http"
                or redirect.hostname != "127.0.0.1"
                or not redirect.port
                or redirect.path != "/auth/callback"
                or redirect.query
                or redirect.fragment
                or redirect.username
                or redirect.password
            ):
                raise _error("callback_invalid")
            state, nonce, verifier = (
                secrets.token_urlsafe(32),
                secrets.token_urlsafe(32),
                secrets.token_urlsafe(64),
            )
            params = {
                "client_id": saved_client or "dynamic_agent_client",
                "ext_agent_host_id": host_id,
                "response_type": "code",
                "redirect_uri": listener.redirect_uri,
                "scope": SCOPES,
                "resource": RESOURCE,
                "state": state,
                "nonce": nonce,
                "code_challenge_method": "S256",
                "code_challenge": _b64(
                    hashlib.sha256(verifier.encode("ascii")).digest()
                ),
            }
            if selected:
                if selected["tokens"].get("id_token"):
                    params["id_token_hint"] = selected["tokens"]["id_token"]
                if selected["email"]:
                    params["login_hint"] = selected["email"]
                if selected["tokens"] and not PLAN_SCOPES.issubset(
                    selected["tokens"]["scopes"]
                ):
                    params["prompt"] = "consent"
            elif not saved_client:
                params["agent_name_hint"] = "Clarify"
            check()
            try:
                opened = open_browser(AUTHORIZE_ENDPOINT + "?" + urlencode(params))
            except Exception:
                raise _error("browser_failed") from None
            if opened is False:
                raise _error("browser_failed")
            result = listener.wait(check=check)
            check()
            code, client_id = _callback(
                result,
                listener.redirect_uri,
                state,
                saved_client,
            )
            if not saved_client:
                # The code is single-use. Keep only its issued registration so
                # a failed or interrupted exchange can use fresh authorization.
                with self._transaction(check):
                    data = copy.deepcopy(self._data)
                    data["pending_client_id"] = client_id
                    self._save_locked(data)
            payload = self._request(
                "POST",
                TOKEN_ENDPOINT,
                check=check,
                data={
                    "grant_type": "authorization_code",
                    "client_id": client_id,
                    "code": code,
                    "code_verifier": verifier,
                    "redirect_uri": listener.redirect_uri,
                    "resource": RESOURCE,
                },
            )
            claims = self._identity(
                payload.get("id_token"), client_id, nonce, discovery, check
            )
            if selected and claims["sub"] != selected["subject"]:
                raise _error("registration_mismatch")
            tokens = self._token_set(payload)
            account_id = _account_id(claims["sub"], client_id)
            with self._transaction(check):
                data = copy.deepcopy(self._data)
                previous = data["accounts"].get(account_id, {})
                data["accounts"][account_id] = {
                    "issuer": ISSUER,
                    "subject": claims["sub"],
                    "client_id": client_id,
                    "email": claims.get("email", ""),
                    "tokens": tokens,
                    "plan_notice_seen": bool(previous.get("plan_notice_seen", False)),
                }
                data["active"] = account_id
                if data.get("pending_client_id") == client_id:
                    data.pop("pending_client_id")
                self._save_locked(data)
                self._local_signouts.discard(account_id)
                self._invalidate_locked()
        except ChatGPTPlanError:
            raise
        except Exception:
            raise _error("authorization_failed") from None
        finally:
            _close(listener)
            with self._lock:
                if self._attempt is attempt:
                    self._attempt = None

    def check_current(self, generation: int) -> None:
        with self._lock:
            self._load_locked()
            if generation != self._generation or not self._tokens_locked(
                self._selected_locked()
            ):
                raise _error("stale_session")

    def select_account(self, account_id: str) -> None:
        with self._transaction():
            if account_id not in self._data["accounts"]:
                raise _error("unknown_account")
            data = copy.deepcopy(self._data)
            data["active"] = account_id
            self._save_locked(data)
            self._invalidate_locked()

    def acknowledge_plan_notice(self) -> None:
        with self._transaction():
            record = self._selected_locked()
            tokens = self._tokens_locked(record)
            if not tokens or not PLAN_SCOPES.issubset(tokens["scopes"]):
                raise _error("plan_disabled")
            if not record.get("plan_notice_seen", False):
                data = copy.deepcopy(self._data)
                data["accounts"][data["active"]]["plan_notice_seen"] = True
                self._save_locked(data)

    def credential(self, *, cancel_token=None) -> ChatGPTCredential:
        _check_cancel(cancel_token)
        with self._lock:
            self._load_locked()
            generation = self._generation
            if not self._tokens_locked(self._selected_locked()):
                raise _error("sign_in_required")

        def check():
            _check_cancel(cancel_token)
            self.check_current(generation)

        while not self._refresh_lock.acquire(timeout=0.05):
            check()
        try:
            with self._transaction(check):
                record = self._selected_locked()
                tokens = self._tokens_locked(record)
                if not PLAN_SCOPES.issubset(tokens["scopes"]):
                    raise _error("plan_disabled")
                if record.get("refresh_pending"):
                    raise _error("refresh_failed")
                now = self._clock()
                if tokens["expires_at"] > now + 60 or (
                    now < tokens.get("earliest_refresh_at", 0)
                    and tokens["expires_at"] > now
                ):
                    return ChatGPTCredential(
                        tokens["access_token"], generation, self._data["active"]
                    )
                if now < tokens.get("earliest_refresh_at", 0):
                    raise _error("refresh_failed")
                account_id, client_id = self._data["active"], record["client_id"]
                tokens = copy.deepcopy(tokens)
                claim = secrets.token_urlsafe(24)
                data = copy.deepcopy(self._data)
                data["accounts"][account_id]["refresh_pending"] = claim
                self._save_locked(data)
            # No HTTP retry: this claim survives an uncertain send or a crash.
            payload = self._request(
                "POST",
                TOKEN_ENDPOINT,
                check=check,
                data={
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "refresh_token": tokens["refresh_token"],
                    "resource": RESOURCE,
                },
            )
            replacement = self._token_set(payload, previous=tokens)
            if "id_token" in payload:
                claims = self._identity(
                    payload["id_token"], client_id, None, self._discovery(check), check
                )
                if claims["sub"] != record["subject"]:
                    raise _error("registration_mismatch")
            with self._transaction(check):
                if self._data["accounts"][account_id].get("refresh_pending") != claim:
                    raise _error("stale_session")
                data = copy.deepcopy(self._data)
                data["accounts"][account_id]["tokens"] = replacement
                del data["accounts"][account_id]["refresh_pending"]
                self._save_locked(data)
                if not PLAN_SCOPES.issubset(replacement["scopes"]):
                    raise _error("plan_disabled")
                return ChatGPTCredential(
                    replacement["access_token"], generation, account_id
                )
        except ChatGPTPlanError as error:
            if (
                isinstance(error, _OAuthResponseError)
                and error.oauth_code in _TERMINAL_REFRESH_CODES
            ):
                with self._transaction(check):
                    data = copy.deepcopy(self._data)
                    record = data["accounts"][account_id]
                    if record.get("refresh_pending") != claim:
                        raise _error("stale_session")
                    self._local_signouts.add(account_id)
                    self._invalidate_locked()
                    record["tokens"] = {}
                    record.pop("refresh_pending", None)
                    self._save_locked(data)
                raise _error("sign_in_required") from None
            if error.code in {
                "cancelled",
                "stale_session",
                "plan_disabled",
                "sign_in_required",
                "storage_unavailable",
                "storage_invalid",
            }:
                raise
            raise _error("refresh_failed") from None
        finally:
            self._refresh_lock.release()

    def sign_out(self) -> None:
        # Invalidate publication before HTTP. A late refresh cannot restore use.
        storage_error = False
        refresh = client_id = ""
        try:
            with self._transaction():
                self._local_signouts.add(self._data["active"])
                self._invalidate_locked()
                record = self._selected_locked()
                if record:
                    refresh = record["tokens"].get("refresh_token", "")
                    client_id = record["client_id"]
                    data = copy.deepcopy(self._data)
                    data["accounts"][data["active"]]["tokens"] = {}
                    data["accounts"][data["active"]].pop("refresh_pending", None)
                    self._save_locked(data)
        except ChatGPTPlanError:
            storage_error = True
        revocation_error = False
        if refresh:
            try:
                discovery = self._discovery()
                url = _endpoint(discovery.get("revocation_endpoint"))
                self._request(
                    "POST",
                    url,
                    empty=True,
                    data={
                        "token": refresh,
                        "token_type_hint": "refresh_token",
                        "client_id": client_id,
                    },
                )
            except ChatGPTPlanError:
                revocation_error = True
        if storage_error:
            raise _error("storage_unavailable")
        if revocation_error:
            raise _error("revocation_failed")


_SESSIONS = {}
_SESSIONS_LOCK = threading.Lock()


def get_chatgpt_session(data_directory: Path | None = None) -> ChatGPTPlanSession:
    if data_directory is None:
        if os.environ.get("CLARIFY_DATA_DIR"):
            data_directory = Path(os.environ["CLARIFY_DATA_DIR"])
        elif os.name == "nt":
            data_directory = (
                Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
                / "Clarify"
            )
        else:
            data_directory = Path.home() / ".clarify"
    directory = Path(data_directory).resolve()
    key = os.path.normcase(str(directory))
    with _SESSIONS_LOCK:
        if key not in _SESSIONS:
            _SESSIONS[key] = ChatGPTPlanSession(directory)
        return _SESSIONS[key]
