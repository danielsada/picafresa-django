import pytest
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from organizations.models import AssistanceProvider, Business, Reseller, ScopedAssignment
from organizations.selectors import can_access_reseller


@pytest.mark.journey
class OrganizationAdminJourneyTests(TestCase):
    def setUp(self) -> None:
        self.operator = User.objects.create_superuser(
            email="operator@example.com",
            password="test-password",
        )
        self.client.force_login(self.operator)

    def test_platform_operator_can_create_and_inspect_organizations(self) -> None:
        response = self.client.post(
            reverse("admin:organizations_reseller_add"),
            {"name": "Socio Norte", "is_active": "on"},
            follow=True,
        )

        self.assertContains(response, "Socio Norte")

        response = self.client.post(
            reverse("admin:organizations_business_add"),
            {
                "name": "Empresa Gemela",
                "reseller": "1",
                "timezone": "America/Mexico_City",
                "is_active": "on",
            },
            follow=True,
        )

        self.assertContains(response, "Empresa Gemela")

        response = self.client.post(
            reverse("admin:organizations_assistanceprovider_add"),
            {
                "name": "Asistencia Uno",
                "contact_name": "Mesa de ayuda",
                "contact_email": "ayuda@example.com",
                "contact_phone": "+52 55 5555 0101",
                "service_instructions": "Llama y menciona tu Póliza.",
                "is_active": "on",
            },
            follow=True,
        )

        self.assertContains(response, "Asistencia Uno")

    def test_platform_operator_can_override_provider_contacts_for_one_business(self) -> None:
        reseller = Reseller.objects.create(name="Socio Norte")
        business = Business.objects.create(name="Empresa Gemela", reseller=reseller)
        provider = AssistanceProvider.objects.create(
            name="Asistencia Uno",
            contact_phone="+52 55 5555 0101",
        )

        response = self.client.post(
            reverse("admin:organizations_providerassignment_add"),
            {
                "business": str(business.pk),
                "provider": str(provider.pk),
                "contact_name_override": "Línea Empresa Gemela",
                "contact_email_override": "gemela@example.com",
                "contact_phone_override": "+52 55 5555 0202",
                "service_instructions_override": "Marca la opción dos.",
                "is_active": "on",
            },
            follow=True,
        )

        self.assertContains(response, "Empresa Gemela")
        self.assertContains(response, "Asistencia Uno")
        self.assertContains(response, "+52 55 5555 0202")

    def test_platform_operator_must_use_an_iana_business_timezone(self) -> None:
        reseller = Reseller.objects.create(name="Socio Norte")

        response = self.client.post(
            reverse("admin:organizations_business_add"),
            {
                "name": "Empresa Fuera de Zona",
                "reseller": str(reseller.pk),
                "timezone": "Mexico/Not_A_Zone",
                "is_active": "on",
            },
        )

        self.assertContains(response, "zona horaria IANA válida")
        changelist = self.client.get(reverse("admin:organizations_business_changelist"))
        self.assertNotContains(changelist, "Empresa Fuera de Zona")

    def test_platform_operator_can_grant_and_revoke_audited_scope(self) -> None:
        reseller = Reseller.objects.create(name="Socio Norte")
        scoped_user = User.objects.create_user(email="north.admin@example.com")

        response = self.client.post(
            reverse("admin:organizations_scopedassignment_add"),
            {
                "user": str(scoped_user.pk),
                "role": ScopedAssignment.Role.RESELLER_ADMIN,
                "reseller": str(reseller.pk),
            },
            follow=True,
        )

        self.assertContains(response, "north.admin@example.com")
        self.assertTrue(can_access_reseller(scoped_user, reseller))
        audit_response = self.client.get(reverse("admin:audit_auditevent_changelist"))
        self.assertContains(audit_response, "assignment.granted")
        self.assertContains(audit_response, "operator@example.com")

        assignment = ScopedAssignment.objects.get(user=scoped_user)
        response = self.client.post(
            reverse(
                "admin:organizations_scopedassignment_delete",
                args=(assignment.pk,),
            ),
            {"post": "yes"},
            follow=True,
        )

        self.assertContains(response, "north.admin@example.com")
        self.assertFalse(can_access_reseller(scoped_user, reseller))
        audit_response = self.client.get(reverse("admin:audit_auditevent_changelist"))
        self.assertContains(audit_response, "assignment.revoked")

    def test_platform_operator_soft_deletes_organization_with_audit_evidence(self) -> None:
        reseller = Reseller.objects.create(name="Socio Retirado")

        response = self.client.post(
            reverse("admin:organizations_reseller_delete", args=(reseller.pk,)),
            {"post": "yes"},
            follow=True,
        )

        self.assertContains(response, "Socio Retirado")
        audit_response = self.client.get(reverse("admin:audit_auditevent_changelist"))
        self.assertContains(audit_response, "organization.soft_deleted")
        self.assertContains(audit_response, "operator@example.com")

    def test_scoped_user_cannot_enter_platform_admin_even_with_staff_flag(self) -> None:
        reseller = Reseller.objects.create(name="Socio Norte")
        scoped_user = User.objects.create_user(
            email="north.admin@example.com",
            password="test-password",
            is_staff=True,
        )
        ScopedAssignment.objects.create(
            user=scoped_user,
            role=ScopedAssignment.Role.RESELLER_ADMIN,
            reseller=reseller,
        )
        self.client.force_login(scoped_user)

        response = self.client.get(reverse("admin:index"))

        self.assertRedirects(
            response,
            f"{reverse('admin:login')}?next={reverse('admin:index')}",
            fetch_redirect_response=False,
        )
