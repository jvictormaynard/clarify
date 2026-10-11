from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from django.conf import settings
from django.http import JsonResponse

from .middleware import take_rate


class AccountAdapter(DefaultAccountAdapter):
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
