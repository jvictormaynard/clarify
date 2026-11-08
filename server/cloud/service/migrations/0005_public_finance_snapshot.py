from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("service", "0004_weekly_funding")]
    operations = [
        migrations.CreateModel(
            name="PublicFinanceSnapshot",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("configuration_tag", models.CharField(default="", max_length=64)),
                ("synced_at", models.DateTimeField(null=True)),
                ("attempted_at", models.DateTimeField(null=True)),
                ("error_code", models.CharField(default="", max_length=24)),
                ("history_complete", models.BooleanField(default=False)),
                ("generation", models.PositiveBigIntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name="PublicStripeBalance",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("currency", models.CharField(max_length=3)),
                ("available_minor", models.BigIntegerField()),
                ("pending_minor", models.BigIntegerField()),
                (
                    "snapshot",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="service.publicfinancesnapshot",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("snapshot", "currency"), name="public_stripe_currency"
                    )
                ]
            },
        ),
        migrations.CreateModel(
            name="PublicStripeMovement",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("position", models.PositiveIntegerField()),
                ("occurred_at", models.DateTimeField()),
                ("available_on", models.DateTimeField()),
                ("kind", models.CharField(max_length=24)),
                ("currency", models.CharField(max_length=3)),
                ("amount_minor", models.BigIntegerField()),
                ("fee_minor", models.BigIntegerField()),
                ("net_minor", models.BigIntegerField()),
                ("availability", models.CharField(max_length=12)),
                (
                    "snapshot",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="service.publicfinancesnapshot",
                    ),
                ),
            ],
            options={
                "ordering": ["position"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("snapshot", "position"), name="public_stripe_position"
                    )
                ],
            },
        ),
    ]
