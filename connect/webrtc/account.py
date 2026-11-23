"""Read-only validation against the existing Clarify account endpoint."""

import json
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID
from .control import Rejected


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class AccountValidator:
    def __init__(self, origin):
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError("Account origin must be a fixed HTTPS origin")
        self.origin = origin.rstrip("/")

    def __call__(self, authorization):
        if not isinstance(authorization, str) or not authorization.startswith(
            "Bearer "
        ):
            raise Rejected("unauthorized")
        token = authorization[7:]
        if not 1 <= len(token) <= 4096 or any(
            ord(c) < 33 or ord(c) > 126 for c in token
        ):
            raise Rejected("unauthorized")
        request = Request(
            self.origin + "/v1/account",
            headers={"X-Session-Token": token, "Accept": "application/json"},
        )
        try:
            # No redirect can forward the account credential to another origin.
            with build_opener(NoRedirect()).open(request, timeout=5) as response:
                if response.status != 200:
                    raise ValueError()
                body = response.read(131073)
                if len(body) > 131072:
                    raise ValueError()
                identity = str(UUID(json.loads(body)["id"]))
        except Exception:
            raise Rejected("unauthorized") from None
        return self.origin + "/" + identity
