from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import User
from audit.models import AuditEvent
from organizations.models import (
    AssistanceProvider,
    Reseller,
    ScopedAssignment,
)
from organizations.selectors import (
    accessible_businesses,
    can_access_business,
    can_access_provider,
    can_access_reseller,
)
from organizations.services import revoke_assignment, soft_delete_organization
from tests.builders import (
    create_business,
    create_provider_assignment,
    create_provider_scope,
    create_reseller_scope,
    create_tenant_scope,
)


class OrganizationAuthorizationTests(TestCase):
    def setUp(self) -> None:
        self.north = Reseller.objects.create(name="Socio Norte")
        self.south = Reseller.objects.create(name="Socio Sur")
        self.north_business = create_business(
            name="Empresa Gemela",
            reseller=self.north,
        )
        self.south_business = create_business(
            name="Empresa Gemela",
            reseller=self.south,
        )
        self.provider = AssistanceProvider.objects.create(name="Asistencia Uno")
        self.north_provider_assignment = create_provider_assignment(
            business=self.north_business,
            provider=self.provider,
        )
        self.south_provider_assignment = create_provider_assignment(
            business=self.south_business,
            provider=self.provider,
        )

    def test_reseller_assignment_cannot_cross_portfolio_boundary(self) -> None:
        user = User.objects.create_user(email="north.admin@example.com")
        create_reseller_scope(
            user=user,
            reseller=self.north,
        )

        self.assertTrue(can_access_reseller(user, self.north))
        self.assertFalse(can_access_reseller(user, self.south))
        self.assertTrue(can_access_business(user, self.north_business))
        self.assertFalse(can_access_business(user, self.south_business))
        self.assertQuerySetEqual(
            accessible_businesses(user),
            [self.north_business],
        )

    def test_provider_assignment_grants_only_its_provider_tenant_context(self) -> None:
        user = User.objects.create_user(email="provider.employee@example.com")
        create_provider_scope(
            user=user,
            provider_assignment=self.north_provider_assignment,
        )

        self.assertTrue(can_access_provider(user, self.provider, self.north_business))
        self.assertFalse(can_access_provider(user, self.provider, self.south_business))
        self.assertTrue(can_access_business(user, self.north_business))
        self.assertFalse(can_access_business(user, self.south_business))
        self.assertFalse(can_access_reseller(user, self.north))

    def test_composable_assignments_union_scopes_without_broadening_each_role(self) -> None:
        user = User.objects.create_user(email="multi.scope@example.com")
        create_tenant_scope(
            user=user,
            business=self.north_business,
        )
        create_provider_scope(
            user=user,
            provider_assignment=self.south_provider_assignment,
        )

        self.assertQuerySetEqual(
            accessible_businesses(user),
            [self.north_business, self.south_business],
            ordered=False,
        )
        self.assertFalse(can_access_reseller(user, self.north))
        self.assertFalse(can_access_reseller(user, self.south))

    def test_revoked_scope_can_be_granted_again_without_losing_audit_history(self) -> None:
        operator = User.objects.create_superuser(email="operator@example.com")
        user = User.objects.create_user(email="north.admin@example.com")
        assignment = create_reseller_scope(
            user=user,
            reseller=self.north,
            granted_by=operator,
        )

        revoke_assignment(assignment, operator)
        replacement = create_reseller_scope(
            user=user,
            reseller=self.north,
            granted_by=operator,
        )

        self.assertNotEqual(replacement.pk, assignment.pk)
        self.assertTrue(can_access_reseller(user, self.north))
        event = AuditEvent.objects.get(action="assignment.revoked")
        self.assertEqual(event.actor, operator)
        self.assertEqual(event.active_scope_type, "reseller")
        self.assertEqual(event.active_scope_reference, str(self.north.pk))

    def test_database_rejects_role_with_mismatched_scope(self) -> None:
        user = User.objects.create_user(email="invalid.scope@example.com")

        with self.assertRaises(IntegrityError), transaction.atomic():
            ScopedAssignment.objects.create(
                user=user,
                role=ScopedAssignment.Role.RESELLER_ADMIN,
                business=self.north_business,
            )

    def test_scoped_user_cannot_mutate_organization_outside_platform_admin(self) -> None:
        user = User.objects.create_user(email="north.admin@example.com")
        create_reseller_scope(
            user=user,
            reseller=self.north,
        )

        with self.assertRaises(PermissionDenied):
            soft_delete_organization(self.south_business, user)

        self.south_business.refresh_from_db()
        self.assertTrue(self.south_business.is_active)
        self.assertIsNone(self.south_business.deleted_at)

    def test_scoped_user_cannot_revoke_another_users_assignment(self) -> None:
        user = User.objects.create_user(email="north.admin@example.com")
        other_user = User.objects.create_user(email="south.admin@example.com")
        create_reseller_scope(
            user=user,
            reseller=self.north,
        )
        other_assignment = create_reseller_scope(
            user=other_user,
            reseller=self.south,
        )

        with self.assertRaises(PermissionDenied):
            revoke_assignment(other_assignment, user)

        other_assignment.refresh_from_db()
        self.assertIsNone(other_assignment.revoked_at)
