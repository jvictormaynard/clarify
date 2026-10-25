"""Small bounded cleanup, invoked by the API worker and a manual command."""

from datetime import timedelta

from django.contrib.sessions.models import Session
from django.utils import timezone

from .ledger import expire_leases
from .models import Operation, RateBucket


def maintain():
    from .social import expire_attempts

    expire_attempts()
    expire_leases()
    now = timezone.now()
    Operation.objects.filter(result_expires_at__lt=now).exclude(result={}).update(
        result={}
    )
    # Keep idempotency and accounting metadata, without text, for 31 days.
    Operation.objects.exclude(state="running").filter(
        created_at__lt=now - timedelta(days=31)
    ).delete()
    RateBucket.objects.filter(expires_at__lt=now).delete()
    Session.objects.filter(expire_date__lt=now).delete()
