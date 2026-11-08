"""Public finance projection. Never store provider objects, identifiers or prose."""

from django.db import models


class PublicFinanceSnapshot(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    # HMAC scopes this projection to the configured credential without storing it.
    configuration_tag = models.CharField(max_length=64, default="")
    synced_at = models.DateTimeField(null=True)
    attempted_at = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=24, default="")
    history_complete = models.BooleanField(default=False)
    generation = models.PositiveBigIntegerField(default=0)


class PublicStripeBalance(models.Model):
    snapshot = models.ForeignKey(PublicFinanceSnapshot, on_delete=models.CASCADE)
    currency = models.CharField(max_length=3)
    available_minor = models.BigIntegerField()
    pending_minor = models.BigIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "currency"], name="public_stripe_currency"
            )
        ]


class PublicStripeMovement(models.Model):
    snapshot = models.ForeignKey(PublicFinanceSnapshot, on_delete=models.CASCADE)
    position = models.PositiveIntegerField()
    occurred_at = models.DateTimeField()
    available_on = models.DateTimeField()
    kind = models.CharField(max_length=24)
    currency = models.CharField(max_length=3)
    amount_minor = models.BigIntegerField()
    fee_minor = models.BigIntegerField()
    net_minor = models.BigIntegerField()
    availability = models.CharField(max_length=12)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "position"], name="public_stripe_position"
            )
        ]
