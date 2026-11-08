"""Keep administrator browser sessions separate from native client tokens."""

from datetime import datetime, timezone

from allauth.headless.tokens.strategies.sessions import SessionTokenStrategy
from django.db import transaction
from django.utils.crypto import salted_hmac

from .models import RateBucket


class ScopedSessionTokenStrategy(SessionTokenStrategy):
    def lookup_session(self, session_token):
        session = super().lookup_session(session_token)
        if session is not None and (
            "clarify_admin_pending" in session
            or "clarify_admin_authenticated_at" in session
            or "clarify_social_handoff" in session
            or "clarify_social_browser" in session
        ):
            return None
        return session


def take_confirmation_attempt(pending):
    """Five attempts per issued challenge, without a fixed-window reset."""
    key = salted_hmac("clarify-admin-attempt", pending["nonce"]).hexdigest()
    expires = datetime.fromtimestamp(pending["issued_at"] + 600, tz=timezone.utc)
    with transaction.atomic():
        RateBucket.objects.get_or_create(key=key, defaults={"expires_at": expires})
        bucket = RateBucket.objects.select_for_update().get(key=key)
        if bucket.count >= 5:
            return False
        bucket.count += 1
        bucket.save(update_fields=["count"])
    return True
