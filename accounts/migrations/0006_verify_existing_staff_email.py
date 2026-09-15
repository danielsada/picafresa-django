from django.db import migrations
from django.utils import timezone


def verify_existing_staff_email(apps, schema_editor):
    del schema_editor
    user = apps.get_model("accounts", "User")
    user.objects.filter(
        is_staff=True,
        email_verified_at__isnull=True,
    ).update(email_verified_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_accountproof_requested_email_and_more"),
    ]

    operations = [
        migrations.RunPython(verify_existing_staff_email, migrations.RunPython.noop),
    ]
