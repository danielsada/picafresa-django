from datetime import date

import pytest
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from catalog.services import DraftTerms, ServiceTerms, create_draft, create_plan, publish_draft
from enrollments.models import Member, PlanEnrollment
from organizations.models import AssistanceProvider, Reseller
from tests.builders import (
    create_business,
    create_provider_assignment,
    create_provider_scope,
    create_reseller_scope,
)


@pytest.mark.journey
class EnrollmentJourneyTests(TestCase):
    def setUp(self) -> None:
        self.reseller = Reseller.objects.create(name="Socio Norte")
        self.business = create_business(name="Empresa Norte", reseller=self.reseller)
        self.provider = AssistanceProvider.objects.create(
            name="Asistencia Norte",
            contact_phone="+52 55 0101",
            service_instructions="Llama con tu Póliza.",
        )
        self.contract = create_provider_assignment(
            business=self.business,
            provider=self.provider,
        )
        self.author = User.objects.create_user(
            email="author@example.test", email_verified_at=timezone.now()
        )
        self.reviewer = User.objects.create_user(
            email="reviewer@example.test", email_verified_at=timezone.now()
        )
        create_reseller_scope(user=self.author, reseller=self.reseller)
        create_reseller_scope(user=self.reviewer, reseller=self.reseller)
        self.member = Member.objects.create(business=self.business, full_name="María Ejemplo")
        self.plan = create_plan(
            actor=self.author,
            reseller_id=self.reseller.pk,
            provider_id=self.provider.pk,
            name="Plan Familiar",
        )
        version = create_draft(
            actor=self.author,
            plan_id=self.plan.pk,
            terms=DraftTerms(
                date(2026, 1, 1),
                date(2030, 1, 1),
                1,
                "Cobertura familiar.",
                (ServiceTerms("Consulta", "Orientación médica."),),
            ),
        )
        publish_draft(actor=self.reviewer, version_id=version.pk)

    def test_reseller_creates_transitions_and_renews_a_poliza(self) -> None:
        self.client.force_login(self.author)
        business_url = f"/cartera/empresas/{self.business.pk}/"
        page = self.client.get(business_url)
        self.assertContains(page, "Pólizas")
        created = self.client.post(
            f"{business_url}polizas/nueva/",
            {
                "member": self.member.pk,
                "plan": self.plan.pk,
                "start_date": "2027-01-31",
            },
            follow=True,
        )
        self.assertEqual(len(created.redirect_chain), 1)
        enrollment_url = created.redirect_chain[0][0]
        self.assertContains(created, "María Ejemplo")
        self.assertContains(created, "31 de Enero de 2027")
        self.assertContains(created, "28 de Febrero de 2027 (exclusivo)")
        self.assertContains(created, "America/Mexico_City")

        activated = self.client.post(
            f"{enrollment_url}estado/",
            {"status": PlanEnrollment.Status.ACTIVE},
            follow=True,
        )
        self.assertContains(activated, "Activa")

        self.plan.auto_renew_enabled = True
        self.plan.save(update_fields=["auto_renew_enabled"])
        renewed = self.client.post(f"{enrollment_url}renovar/", follow=True)
        self.assertContains(renewed, "Póliza renovada")
        renewal = PlanEnrollment.objects.get(preceding_enrollment__isnull=False)
        self.assertEqual(renewal.start_date, date(2027, 2, 28))

    def test_provider_employee_cannot_use_or_override_enrollment_workflow(self) -> None:
        provider_employee = User.objects.create_user(
            email="provider@example.test", email_verified_at=timezone.now()
        )
        create_provider_scope(user=provider_employee, provider_assignment=self.contract)
        self.client.force_login(provider_employee)

        response = self.client.post(
            f"/cartera/empresas/{self.business.pk}/polizas/nueva/",
            {
                "member": self.member.pk,
                "plan": self.plan.pk,
                "start_date": "2027-01-31",
                "explicit_end_date": "2027-03-01",
                "allow_eligibility_override": "on",
                "override_reason": "Excepción solicitada.",
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(PlanEnrollment.objects.exists())

    def test_platform_operator_can_inspect_enrollments_in_admin(self) -> None:
        operator = User.objects.create_superuser(email="operator@example.test")
        self.client.force_login(self.author)
        self.client.post(
            f"/cartera/empresas/{self.business.pk}/polizas/nueva/",
            {
                "member": self.member.pk,
                "plan": self.plan.pk,
                "start_date": "2027-01-31",
            },
        )
        self.client.force_login(operator)

        response = self.client.get(reverse("admin:enrollments_planenrollment_changelist"))

        self.assertContains(response, "María Ejemplo")
        self.assertContains(response, "Plan Familiar")
