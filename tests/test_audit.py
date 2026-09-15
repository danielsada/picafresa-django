from django.db import DatabaseError, connection, transaction
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

    def test_database_rejects_audit_event_update_and_delete(self) -> None:
        user = User.objects.create_user(email="database.audit@example.com")
        event = AuditEvent.objects.create(
            actor=user,
            action="account.tested",
            object_type="user",
            object_reference=str(user.pk),
            changes={"safe": True},
        )

        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "UPDATE audit_auditevent SET action = %s WHERE id = %s",
                ["account.tampered", event.pk],
            )
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM audit_auditevent WHERE id = %s",
                [event.pk],
            )

        event.refresh_from_db()
        self.assertEqual(event.action, "account.tested")
