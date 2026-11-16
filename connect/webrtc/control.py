"""Bounded signaling state. Inject account validation; never accept account IDs from clients."""

from __future__ import annotations

import base64
from contextlib import closing
import hashlib
import hmac
import json
import secrets
import threading
import time


SETUP_TTL = 120
SESSION_IDLE_TTL = 90
TURN_TTL = 900


class Rejected(ValueError):
    pass


class Control:
    """One process, bounded volatile sessions. Restart requires fresh session tickets.

    Account validator returns a stable issuer+subject or raises. Its owner must
    validate expiry, audience, signature and account revocation on every call.
    Enrollment is explicit and must use the existing account's device approval.
    """

    def __init__(
        self,
        account,
        *,
        turn_secret: bytes,
        turn_urls: list[str],
        clock=time.time,
        database=None,
    ):
        if len(turn_secret) < 32:
            raise ValueError("TURN secret must contain at least 32 bytes")
        self.account, self.secret, self.urls, self.clock = (
            account,
            turn_secret,
            turn_urls,
            clock,
        )
        self.hosts, self.sessions = {}, {}
        self.lock = threading.RLock()
        self.database = database
        if database is not None:
            import sqlite3
            from pathlib import Path

            Path(database).parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(database)) as db, db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS hosts (owner TEXT, host TEXT, public TEXT NOT NULL, PRIMARY KEY(owner, host))"
                )
                rows = db.execute(
                    "SELECT owner, host, public FROM hosts LIMIT 4097"
                ).fetchall()
                if len(rows) > 4096:
                    raise ValueError("Enrollment capacity exceeded")
                self.hosts = {
                    (owner, host): json.loads(public) for owner, host, public in rows
                }

    def _persist(self, key, public=None):
        if self.database is None:
            return
        import sqlite3

        with closing(sqlite3.connect(self.database)) as db, db:
            if public is None:
                db.execute("DELETE FROM hosts WHERE owner=? AND host=?", key)
            else:
                db.execute(
                    "INSERT INTO hosts VALUES (?, ?, ?)", (*key, json.dumps(public))
                )

    def call(self, bearer, value):
        if not isinstance(value, dict) or len(json.dumps(value).encode()) > 131072:
            raise Rejected("invalid_request")
        owner = self.account(bearer)
        if not owner:
            raise Rejected("unauthorized")
        with self.lock:
            now = self.clock()
            self.sessions = {
                k: v for k, v in self.sessions.items() if v["expires"] > now
            }
            action, host = value.get("action"), value.get("host")
            key = (owner, host)
            if not isinstance(host, str) or not 1 <= len(host) <= 100:
                raise Rejected("invalid_host")
            if action == "enroll":
                public = value.get("public_key")
                if not isinstance(public, dict) or len(json.dumps(public)) > 1024:
                    raise Rejected("invalid_key")
                try:
                    from cryptography.hazmat.primitives.asymmetric import ec

                    if (
                        public.get("kty") != "EC"
                        or public.get("crv") != "P-256"
                        or "d" in public
                    ):
                        raise ValueError()
                    coordinates = [
                        int.from_bytes(
                            base64.urlsafe_b64decode(
                                public[c] + "=" * (-len(public[c]) % 4)
                            ),
                            "big",
                        )
                        for c in ("x", "y")
                    ]
                    ec.EllipticCurvePublicNumbers(
                        *coordinates, ec.SECP256R1()
                    ).public_key()
                    public = {k: public[k] for k in ("kty", "crv", "x", "y")}
                except Exception:
                    raise Rejected("invalid_key") from None
                if key in self.hosts and self.hosts[key] == public:
                    return {"registered": True}
                if key in self.hosts or len(self.hosts) >= 4096:
                    raise Rejected("host_exists_or_capacity")
                self._persist(key, public)
                self.hosts[key] = public
                return {"registered": True}
            if action == "revoke":
                self._persist(key)
                self.hosts.pop(key, None)
                self.sessions = {
                    k: s
                    for k, s in self.sessions.items()
                    if (s["owner"], s["host"]) != key
                }
                return {"revoked": True}
            if key not in self.hosts:
                raise Rejected("host_revoked")
            if action == "pending":
                return {
                    "tickets": [
                        t
                        for t, s in self.sessions.items()
                        if (s["owner"], s["host"]) == key
                        and s["offer"] is not None
                        and s["answer"] is None
                    ]
                }
            if action == "create":
                if (
                    len(self.sessions) >= 1024
                    or sum(s["owner"] == owner for s in self.sessions.values()) >= 8
                ):
                    raise Rejected("capacity")
                ticket = secrets.token_urlsafe(32)
                self.sessions[ticket] = dict(
                    owner=owner,
                    host=host,
                    expires=now + SETUP_TTL,
                    offer=None,
                    answer=None,
                    relay=value.get("relay") is True,
                )
                return {
                    "ticket": ticket,
                    "expires": now + SETUP_TTL,
                    "public_key": self.hosts[key],
                }
            ticket = value.get("ticket")
            session = self.sessions.get(ticket) if isinstance(ticket, str) else None
            if not session or (session["owner"], session["host"]) != key:
                raise Rejected("invalid_ticket")
            if action == "close":
                del self.sessions[ticket]
                return {"closed": True}
            if action == "turn":
                username = f"{int(now + TURN_TTL)}:{hashlib.sha256(ticket.encode()).hexdigest()[:24]}"
                credential = base64.b64encode(
                    hmac.new(self.secret, username.encode(), hashlib.sha1).digest()
                ).decode()
                return {
                    "iceServers": [
                        {
                            "urls": self.urls,
                            "username": username,
                            "credential": credential,
                        }
                    ],
                    "expires": now + TURN_TTL,
                }
            if action == "poll":
                if session["answer"] is not None:
                    # Only an authenticated call can renew an established peer.
                    session["expires"] = now + SESSION_IDLE_TTL
                return {k: session[k] for k in ("offer", "answer", "expires", "relay")}
            if action in ("offer", "answer"):
                payload = value.get("payload")
                if (
                    not isinstance(payload, dict)
                    or len(json.dumps(payload)) > 100000
                    or session[action] is not None
                ):
                    raise Rejected("invalid_or_repeated_signal")
                session[action] = payload
                if action == "answer":
                    session["expires"] = now + SESSION_IDLE_TTL
                return {"accepted": True}
            raise Rejected("invalid_action")
