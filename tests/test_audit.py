from django.test import TestCase

from accounts.models import User
from audit.models import AuditEvent


class AuditEventTests(TestCase):
    def test_authentication_audit_event_is_append_only(self) -> None:
        user = User.objects.create_user(email="audited.member@example.com")
        event = AuditEvent.objects.create(
            actor=user,
            action="account.tested",
            object_type="user",
            object_reference=str(user.pk),
            changes={"safe": True},
        )

        event.action = "account.tampered"
        with self.assertRaises(ValueError):
            event.save()
        with self.assertRaises(ValueError):
            event.delete()
        with self.assertRaises(ValueError):
            AuditEvent.objects.filter(pk=event.pk).update(action="account.tampered")
        with self.assertRaises(ValueError):
            AuditEvent.objects.filter(pk=event.pk).delete()
