import hashlib
import time
from datetime import timedelta

from django.conf import settings
from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone

from .models import RateBucket


def take_rate(namespace, identity, limit, seconds=60):
    now = timezone.now()
    window = int(time.time()) // seconds
    key = hashlib.sha256(
        f"{settings.SECRET_KEY}:{namespace}:{identity}:{window}".encode()
    ).hexdigest()
    with transaction.atomic():
        RateBucket.objects.get_or_create(
            key=key, defaults={"expires_at": now + timedelta(seconds=seconds * 2)}
        )
        bucket = RateBucket.objects.select_for_update().get(key=key)
        if bucket.count >= limit:
            return False
        bucket.count += 1
        bucket.save(update_fields=["count"])
    return True


class RequestLimits:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        def reject(code, status):
            response = JsonResponse({"code": code}, status=status)
            response["Cache-Control"] = "no-store"
            return response

        public_finance = request.path in {
            "/transparency",
            "/transparency/",
            "/v1/public/finances",
        }
        if public_finance:
            ip = request.META.get("REMOTE_ADDR", "unknown")
            if not take_rate("public_finance_global", "all", 600) or not take_rate(
                "public_finance", ip, 60
            ):
                return reject("rate_limited", 429)

        if not public_finance and request.path.startswith(
            ("/v1/", "/_allauth/", "/social/", "/accounts/")
        ):
            audio = request.path == "/v1/dictations"
            maximum = settings.CLARIFY_MAX_UPLOAD_BYTES + 65536 if audio else 512 * 1024
            if request.path == "/v1/meetings/transcriptions":
                maximum = (
                    min(settings.CLARIFY_MAX_UPLOAD_BYTES, 12 * 1024 * 1024) + 65536
                )
            try:
                length = int(request.META.get("CONTENT_LENGTH") or 0)
            except ValueError:
                return reject("invalid_length", 400)
            if length > maximum or length < 0:
                return reject("upload_too_large", 413)
            ip = request.META.get("REMOTE_ADDR", "unknown")
            social_poll = request.path in {
                "/_allauth/app/v1/auth/social/poll",
                "/_allauth/app/v1/auth/social/cancel",
            }
            auth = request.path.startswith("/_allauth/")
            if social_poll:
                if not take_rate("social_poll_global", "all", 2400) or not take_rate(
                    "social_poll", ip, 120
                ):
                    return reject("rate_limited", 429)
            elif auth and not take_rate("auth_global", "all", 200):
                return reject("rate_limited", 429)
            if not social_poll and not take_rate(
                "auth" if auth else "api", ip, 20 if auth else 120
            ):
                return reject("rate_limited", 429)
            if request.path.endswith("/auth/signup") and request.method == "POST":
                if not take_rate("signup", ip, 3, 3600) or not take_rate(
                    "signup_global", "all", 100, 3600
                ):
                    return reject("rate_limited", 429)
        response = self.get_response(request)
        if getattr(request, "clarify_email_limited", False):
            return reject("email_limit", 429)
        if request.path.startswith(("/v1/", "/_allauth/", "/social/", "/accounts/")):
            response["Cache-Control"] = "no-store"
        return response


class BoundedUpload(FileUploadHandler):
    def __init__(self, request=None):
        super().__init__(request)
        self.received = 0

    def receive_data_chunk(self, raw_data, start):
        self.received += len(raw_data)
        if self.received > settings.CLARIFY_MAX_UPLOAD_BYTES:
            raise StopUpload(connection_reset=True)
        return raw_data

    def file_complete(self, file_size):
        return None
