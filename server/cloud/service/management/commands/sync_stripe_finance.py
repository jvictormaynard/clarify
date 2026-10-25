"""Operator scheduling entrypoint. No account or budget mutations."""

from django.core.management.base import BaseCommand, CommandError
from cloud.service.stripe_finance import StripeSyncError, sync


class Command(BaseCommand):
    help = "Sync sanitized live Stripe balances and movements for public transparency."

    def handle(self, *args, **options):
        try:
            snapshot = sync()
        except StripeSyncError as error:
            raise CommandError("Stripe finance sync failed: " + str(error)) from None
        coverage = (
            "complete"
            if snapshot.history_complete
            else "partial (10,000 movement limit)"
        )
        self.stdout.write("Stripe finance snapshot saved; history " + coverage + ".")
