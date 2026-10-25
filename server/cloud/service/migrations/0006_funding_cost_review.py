from django.db import migrations, models


def preserve_receipt_bases(apps, schema_editor):
    Entry = apps.get_model("service", "FundingEntry")
    entries = Entry.objects.using(schema_editor.connection.alias)
    operating = entries.filter(
        kind__in=["operating_expense", "operating_reserve", "operating_release"]
    )
    charge = sum(
        -entry.amount_usd
        if entry.kind == "operating_release"
        else entry.amount_usd - entry.reserve_consumed_usd
        for entry in operating.iterator()
    )
    for receipt in entries.filter(kind="contribution").order_by("occurred_at", "pk"):
        assigned = min(max(0, charge), receipt.amount_usd)
        receipt.processing_basis_usd = receipt.amount_usd - assigned
        receipt.save(update_fields=["processing_basis_usd"])
        charge -= assigned
    if charge != 0:
        raise ValueError("Operating records exceed confirmed contribution bases")


class Migration(migrations.Migration):
    dependencies = [("service", "0005_public_finance_snapshot")]

    operations = [
        migrations.AddField(
            model_name="fundingentry",
            name="processing_ready_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name="fundingentry",
            name="processing_basis_usd",
            field=models.DecimalField(decimal_places=9, default=0, max_digits=18),
        ),
        migrations.RunPython(preserve_receipt_bases, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="fundingentry",
            constraint=models.CheckConstraint(
                condition=models.Q(processing_basis_usd__gte=0)
                & models.Q(processing_basis_usd__lte=models.F("amount_usd"))
                & (models.Q(kind="contribution") | models.Q(processing_basis_usd=0)),
                name="valid_receipt_processing_basis",
            ),
        ),
    ]
