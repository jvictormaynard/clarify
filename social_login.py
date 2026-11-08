"""Proof-bound native sign-in handoff. No profile or browser work at import time."""

from dataclasses import dataclass
import base64
import hashlib
import secrets
import threading
import time
from urllib.parse import urlsplit
import uuid


class SocialLoginError(RuntimeError):
    pass


@dataclass(frozen=True)
class SocialLoginResult:
    token: str
    pending: str = ""
    email: str = ""


def _failure(code):
    code = code if isinstance(code, str) else None
    return SocialLoginError(
        {
            "social_account_exists": "Este e-mail já tem uma conta. Entre com o código enviado por e-mail.",
            "social_signup_closed": "A criação de contas está indisponível no momento.",
            "social_email_required": "Este provedor não informou um e-mail. Entre com seu e-mail.",
        }.get(
            code,
            "Não foi possível entrar com este provedor. Tente novamente ou use seu e-mail.",
        )
    )


def sign_in(
    provider,
    *,
    endpoint,
    request,
    open_browser,
    check_current,
    accept,
    cancel=None,
    clock=time.monotonic,
):
    """Return one validated session, with bounded polling and best-effort cleanup."""
    if provider not in {"google", "microsoft", "github"}:
        raise _failure(None)
    cancel = cancel or threading.Event()

    def check():
        check_current()
        if cancel.is_set():
            raise SocialLoginError("O login foi cancelado.")

    check()
    started = clock()
    verifier = secrets.token_urlsafe(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    status, result = request(
        "POST",
        "/_allauth/app/v1/auth/social/start",
        json={
            "provider": provider,
            "client": "desktop",
            "code_challenge": challenge,
        },
    )
    if status != 200:
        raise _failure(result.get("code"))
    attempt = result.get("attempt_id")
    try:
        if not isinstance(attempt, str) or str(uuid.UUID(attempt)) != attempt:
            raise ValueError()
    except ValueError:
        raise _failure(None) from None
    proof = {"attempt_id": attempt, "code_verifier": verifier}
    completed = False
    handed_token = None
    try:
        check()
        authorization = result.get("authorization_url")
        if not isinstance(authorization, str) or len(authorization) > 4096:
            raise _failure(None)
        target, origin = urlsplit(authorization), urlsplit(endpoint)
        if (
            (
                target.scheme,
                target.hostname,
                target.port or (443 if target.scheme == "https" else 80),
            )
            != (
                origin.scheme,
                origin.hostname,
                origin.port or (443 if origin.scheme == "https" else 80),
            )
            or target.username is not None
            or target.password is not None
            or target.fragment
            or not target.path.startswith("/")
        ):
            raise _failure(None)
        expires, interval = result.get("expires_in"), result.get("interval")
        if (
            type(expires) is not int
            or not 1 <= expires <= 300
            or type(interval) is not int
            or not 1 <= interval <= 30
        ):
            raise _failure(None)
        deadline = started + expires
        try:
            opened = open_browser(authorization)
        except Exception:
            raise SocialLoginError(
                "Não foi possível abrir o navegador. Tente novamente."
            ) from None
        if not opened:
            raise SocialLoginError(
                "Não foi possível abrir o navegador. Tente novamente."
            )
        while True:
            check()
            if clock() >= deadline:
                raise SocialLoginError("O tempo para entrar acabou. Tente novamente.")
            status, result = request(
                "POST", "/_allauth/app/v1/auth/social/poll", json=proof
            )
            meta = result.get("meta")
            meta = meta if isinstance(meta, dict) else {}
            token = meta.get("session_token")
            if (
                status in {200, 401}
                and isinstance(token, str)
                and token
                and len(token) <= 4096
            ):
                handed_token = token
            check()
            if clock() >= deadline:
                raise SocialLoginError("O tempo para entrar acabou. Tente novamente.")
            if status == 202:
                cancel.wait(min(interval, max(0, deadline - clock())))
                continue
            if not isinstance(token, str) or not token or len(token) > 4096:
                raise _failure(result.get("code"))
            if status == 200 and meta.get("is_authenticated") is True:
                accepted = SocialLoginResult(token)
                accept(accepted)
                completed = True
                return accepted
            data = result.get("data")
            if (
                status == 401
                and meta.get("is_authenticated") is False
                and isinstance(data, dict)
            ):
                email = data.get("email")
                if (
                    data.get("pending") == "signup"
                    and isinstance(email, str)
                    and 3 <= len(email) <= 254
                    and "@" in email
                ):
                    accepted = SocialLoginResult(token, "signup", email)
                    accept(accepted)
                    completed = True
                    return accepted
            raise _failure(result.get("code"))
    except (TypeError, ValueError):
        raise _failure(None) from None
    finally:
        if not completed:
            try:
                request("POST", "/_allauth/app/v1/auth/social/cancel", json=proof)
            except Exception:
                # The server expires an abandoned attempt without a local session.
                pass
            if handed_token:
                try:
                    request(
                        "DELETE", "/_allauth/app/v1/auth/session", token=handed_token
                    )
                except Exception:
                    pass
