# Generated for notification claim ownership and lease recovery.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="emailnotification",
            name="claim_token",
            field=models.UUIDField(
                blank=True,
                editable=False,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="emailnotification",
            name="lease_expires_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
            ),
        ),
    ]
