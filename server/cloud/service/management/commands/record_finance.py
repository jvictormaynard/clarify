"""Record confirmed USD receipts, operating expenses and provisions."""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

from cloud.service import funding


class Command(BaseCommand):
    help = "Record available USD cash or an operating expense, reserve or release."

    def add_arguments(self, parser):
        parser.add_argument(
            "kind", choices=["contribution", "expense", "reserve", "release"]
        )
        parser.add_argument("amount_usd")
        parser.add_argument("--reference", required=True)
        parser.add_argument(
            "--occurred-at", required=True, help="UTC ISO 8601 timestamp"
        )
        parser.add_argument("--source", default="manual")

    def handle(self, *args, **options):
        try:
            kwargs = {
                "amount_usd": Decimal(options["amount_usd"]),
                "reference": options["reference"],
                "source": options["source"],
                "occurred_at": datetime.fromisoformat(
                    options["occurred_at"].replace("Z", "+00:00")
                ),
            }
            if options["kind"] == "contribution":
                _, created = funding.record_contribution(**kwargs)
            else:
                _, created = funding.record_operating(kind=options["kind"], **kwargs)
        except (ValueError, InvalidOperation) as error:
            raise CommandError(str(error)) from None
        self.stdout.write("Recorded." if created else "Already recorded.")
