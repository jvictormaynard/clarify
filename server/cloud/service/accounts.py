from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.models import EmailAddress
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.headless.account.views import RequestLoginCodeView
from allauth.headless.base.response import (
    ConflictResponse,
    ForbiddenResponse,
    RateLimitResponse,
)
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.http import JsonResponse
from django.utils.translation import get_language
from shared.localization import translate

from .middleware import take_rate


class ContinueWithEmailView(RequestLoginCodeView):
    """Use allauth's same code/session flow for new and existing accounts."""

    def post(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return ConflictResponse(request)
        email = self.input.cleaned_data["email"].lower()
        users = get_user_model().objects
        if self.input._user is None and not users.filter(email__iexact=email).exists():
            if not settings.CLARIFY_SIGNUP_ENABLED:
                return ForbiddenResponse(request)
            ip = request.META.get("REMOTE_ADDR", "unknown")
            if not take_rate("signup", ip, 3, 3600) or not take_rate(
                "signup_global", "all", 100, 3600
            ):
                return RateLimitResponse(request)
            with transaction.atomic():
                user, created = users.get_or_create(
                    email=email, defaults={"password": make_password(None)}
                )
                if created:
                    EmailAddress.objects.create(
                        user=user, email=email, primary=True, verified=False
                    )
            if user.is_active:
                self.input._user = user
        # A valid code verifies this address before allauth grants the session.
        # Do not create our own codes, token store, or authentication mechanism.
        return super().post(request, *args, **kwargs)


class AccountAdapter(DefaultAccountAdapter):
    def render_mail(self, template_prefix, email, context, headers=None):
        # LocaleMiddleware selects a supported device language from Accept-Language.
        # Allauth still owns code creation, expiry, attempts, and session validation.
        keys = (
            "email_subject",
            "email_intro",
            "email_instructions",
            "email_expiry",
            "email_ignore",
            "email_existing",
            "email_unknown",
        )
        context = {**context, **{key: translate(key, get_language()) for key in keys}}
        return super().render_mail(template_prefix, email, context, headers=headers)

    def send_mail(self, template_prefix, email, context):
        if not take_rate("email_day", "all", settings.CLARIFY_DAILY_EMAIL_LIMIT, 86400):
            # Headless signup converts ImmediateHttpResponse into a generic
            # authentication result; the outer middleware preserves this limit.
            from allauth.core import context as account_context

            account_context.request.clarify_email_limited = True
            raise ImmediateHttpResponse(
                JsonResponse({"code": "email_limit"}, status=429)
            )
        super().send_mail(template_prefix, email, context)

    def is_open_for_signup(self, request):
        return settings.CLARIFY_SIGNUP_ENABLED

    def get_client_ip(self, request):
        # A client cannot reset limits by supplying its own X-Forwarded-For.
        return request.META.get("REMOTE_ADDR", "unknown")
