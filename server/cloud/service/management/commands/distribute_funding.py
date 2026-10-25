from django.core.management.base import BaseCommand

from cloud.service import funding, ledger


class Command(BaseCommand):
    help = "Settle expired reservations and distribute the current Monday UTC quota."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm-operating-costs",
            action="store_true",
            help="Confirm that operating costs for all pending receipts are recorded.",
        )

    def handle(self, *args, **options):
        ledger.expire_leases()
        period = funding.distribute(
            confirm_operating_costs=options["confirm_operating_costs"]
        )
        self.stdout.write(
            "Distribution ready." if period else "No processing cash available."
        )
