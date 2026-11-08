import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("service", "0002_historystate_historyclear_historyentry"),
    ]

    operations = [
        migrations.CreateModel(
            name="SnippetLibrary",
            fields=[
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        serialize=False,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("revision", models.PositiveBigIntegerField(default=0)),
                ("entries", models.JSONField(default=list)),
            ],
        ),
    ]
