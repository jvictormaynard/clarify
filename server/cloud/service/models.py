import uuid
from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower

from .transparency_models import (  # noqa: F401 -- register durable projections
    PublicFinanceSnapshot,
    PublicStripeBalance,
    PublicStripeMovement,
)


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra):
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, **extra):
        return self.create_user(
            email, password, is_staff=True, is_superuser=True, **extra
        )


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = None
    email = models.EmailField(unique=True)
    monthly_audio_ms = models.PositiveBigIntegerField(null=True, blank=True)
    funded_access = models.BooleanField(default=True)
    hosted_requested_at = models.DateTimeField(null=True, blank=True)
    hosted_last_active_at = models.DateTimeField(null=True, blank=True)
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("email"), name="unique_email_casefold")
        ]


class Dictionary(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True
    )
    revision = models.PositiveBigIntegerField(default=0)
    entries = models.JSONField(default=list)


class SnippetLibrary(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True
    )
    revision = models.PositiveBigIntegerField(default=0)
    entries = models.JSONField(default=list)


class HistoryState(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True
    )
    revision = models.PositiveBigIntegerField(default=0)


class HistoryEntry(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    record_id = models.CharField(max_length=128)
    revision = models.PositiveBigIntegerField()
    # NULL is a permanent tombstone: erase text without allowing stale clients
    # to restore it. History is independent of the short-lived billing result.
    payload = models.JSONField(null=True)
    byte_size = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "record_id"], name="one_account_history_entry"
            )
        ]
        indexes = [
            models.Index(fields=["user", "revision"], name="history_user_revision")
        ]


class HistoryClear(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    operation_id = models.UUIDField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "operation_id"], name="one_account_history_clear"
            )
        ]


class Allowance(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    month = models.DateField()
    used_ms = models.PositiveBigIntegerField(default=0)
    reserved_ms = models.PositiveBigIntegerField(default=0)
    operations = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "month"], name="one_monthly_allowance"
            )
        ]


class Budget(models.Model):
    month = models.DateField(primary_key=True)
    spent = models.DecimalField(max_digits=18, decimal_places=9, default=0)
    reserved = models.DecimalField(max_digits=18, decimal_places=9, default=0)


class Operation(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    operation_id = models.UUIDField()
    month = models.DateField()
    fingerprint = models.CharField(max_length=64)
    state = models.CharField(max_length=16, default="running")
    created_at = models.DateTimeField(auto_now_add=True)
    lease_until = models.DateTimeField()
    audio_ms = models.PositiveBigIntegerField()
    reserved_cost = models.DecimalField(max_digits=18, decimal_places=9)
    cost = models.DecimalField(max_digits=18, decimal_places=9, default=0)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    result = models.JSONField(default=dict)
    result_expires_at = models.DateTimeField(null=True)
    quota = models.ForeignKey("WeeklyQuota", on_delete=models.PROTECT, null=True)
    # A reservation is not a charge. Persist the paid work authorized so far
    # before each provider call, including calls whose response may be lost.
    authorized_cost = models.DecimalField(max_digits=18, decimal_places=9, default=0)
    quota_debit = models.DecimalField(max_digits=18, decimal_places=9, default=0)
    cost_estimated = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "operation_id"], name="one_account_operation"
            )
        ]
        indexes = [models.Index(fields=["state", "lease_until"])]


class RateBucket(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)


class Treasury(models.Model):
    """One financial mutex, independent of UTC months and operation retention."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    processing_spent = models.DecimalField(max_digits=18, decimal_places=9, default=0)
    processing_reserved = models.DecimalField(
        max_digits=18, decimal_places=9, default=0
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="one_treasury")
        ]


class FundingEntry(models.Model):
    kind = models.CharField(
        max_length=32,
        choices=[
            ("contribution", "Contribution"),
            ("operating_expense", "Operating expense"),
            ("operating_reserve", "Operating reserve"),
            ("operating_release", "Operating reserve released"),
            ("processing_cost", "Processing cost"),
            ("processing_estimate", "Processing cost (conservative estimate)"),
            (
                "historical_processing_cost",
                "Historical processing costs (date unavailable)",
            ),
        ],
    )
    amount_usd = models.DecimalField(max_digits=18, decimal_places=9)
    reserve_consumed_usd = models.DecimalField(
        max_digits=18, decimal_places=9, default=0
    )
    source = models.CharField(max_length=32)
    reference = models.CharField(max_length=200)
    occurred_at = models.DateTimeField(null=True)
    release_until = models.DateTimeField(null=True)
    processing_ready_at = models.DateTimeField(null=True)
    processing_basis_usd = models.DecimalField(
        max_digits=18, decimal_places=9, default=0
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "reference"], name="one_funding_receipt"
            ),
            models.CheckConstraint(
                condition=models.Q(amount_usd__gt=0), name="positive_funding_entry"
            ),
            models.CheckConstraint(
                condition=models.Q(processing_basis_usd__gte=0)
                & models.Q(processing_basis_usd__lte=models.F("amount_usd"))
                & (models.Q(kind="contribution") | models.Q(processing_basis_usd=0)),
                name="valid_receipt_processing_basis",
            ),
        ]


class FundingPeriod(models.Model):
    start = models.DateTimeField(primary_key=True)
    reset_at = models.DateTimeField()
    released_usd = models.DecimalField(max_digits=18, decimal_places=9)
    regular_share_usd = models.DecimalField(max_digits=18, decimal_places=9)
    newcomers_remaining_usd = models.DecimalField(max_digits=18, decimal_places=9)
    population = models.PositiveIntegerField()


class WeeklyQuota(models.Model):
    # Keep finance totals after account deletion, without retaining identity.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    period = models.ForeignKey(FundingPeriod, on_delete=models.PROTECT)
    allocated_usd = models.DecimalField(max_digits=18, decimal_places=9)
    used_usd = models.DecimalField(max_digits=18, decimal_places=9, default=0)
    reserved_usd = models.DecimalField(max_digits=18, decimal_places=9, default=0)
    operations = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "period"], name="one_weekly_quota"),
        ]


class SocialAttempt(models.Model):
    """One-time transport of an allauth session, never an identity store."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=16)
    client = models.CharField(max_length=8)
    origin = models.CharField(max_length=255)
    challenge = models.CharField(max_length=43)
    launch_digest = models.CharField(max_length=64)
    browser_digest = models.CharField(max_length=64, blank=True)
    browser_session_key = models.CharField(max_length=40, blank=True)
    state = models.CharField(max_length=16, default="created")
    session_key = models.CharField(max_length=40, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    email = models.EmailField(blank=True)
    error = models.CharField(max_length=32, blank=True)
    expires_at = models.DateTimeField(db_index=True)
    next_poll_at = models.DateTimeField(null=True)
