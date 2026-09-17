import re
from datetime import date

import pytest
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from catalog.services import DraftTerms, ServiceTerms, create_draft, create_plan, publish_draft
from enrollments.models import Beneficiary, Member, PlanEnrollment
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

    def test_reseller_adds_and_inspects_a_beneficiary_on_the_exact_poliza(self) -> None:
        self.client.force_login(self.author)
        created = self.client.post(
            f"/cartera/empresas/{self.business.pk}/polizas/nueva/",
            {
                "member": self.member.pk,
                "plan": self.plan.pk,
                "start_date": "2027-01-31",
            },
            follow=True,
        )
        enrollment_url = created.redirect_chain[0][0]

        response = self.client.post(
            f"{enrollment_url}beneficiarios/nuevo/",
            {
                "full_name": "Sofía Ejemplo",
                "relationship": "Hija",
                "date_of_birth": "2015-04-03",
                "country_code": "MX",
                "gender": "female",
                "email": "sofia@example.test",
                "phone": "+52 55 2222",
                "attribution_source": "Registro administrativo",
                "do_not_contact": "on",
            },
            follow=True,
        )

        self.assertRedirects(response, enrollment_url)
        self.assertContains(response, "Sofía Ejemplo")
        self.assertContains(response, "Hija")
        beneficiary = Beneficiary.objects.get()
        self.assertEqual(beneficiary.enrollment.member, self.member)
        self.assertEqual(beneficiary.country_code, "MX")
        self.assertEqual(beneficiary.gender, Beneficiary.Gender.FEMALE)
        self.assertTrue(beneficiary.do_not_contact)
        self.assertFalse(User.objects.filter(email="sofia@example.test").exists())
        event = AuditEvent.objects.get(action="enrollment.beneficiary_added")
        self.assertNotIn("sofia@example.test", str(event.changes))
        self.assertNotIn("+52 55 2222", str(event.changes))

    def test_primary_member_activates_an_invited_account_for_only_their_terms(self) -> None:
        self.member.email = "member@example.test"
        self.member.country_code = "MX"
        self.member.gender = Member.Gender.FEMALE
        self.member.phone = "+52 55 1111"
        self.member.attribution_source = "Carga inicial"
        self.member.do_not_contact = False
        self.member.save()
        other_member = Member.objects.create(
            business=self.business,
            full_name="Otro Afiliado",
            email="other@example.test",
        )
        self.client.force_login(self.author)
        first = self.client.post(
            f"/cartera/empresas/{self.business.pk}/polizas/nueva/",
            {
                "member": self.member.pk,
                "plan": self.plan.pk,
                "start_date": "2027-01-01",
            },
            follow=True,
        )
        first_url = first.redirect_chain[0][0]
        self.client.post(
            f"{first_url}estado/",
            {"status": PlanEnrollment.Status.CANCELLED},
        )
        second = self.client.post(
            f"/cartera/empresas/{self.business.pk}/polizas/nueva/",
            {
                "member": self.member.pk,
                "plan": self.plan.pk,
                "start_date": "2027-02-01",
            },
            follow=True,
        )
        second_url = second.redirect_chain[0][0]
        self.client.post(
            f"{second_url}estado/",
            {"status": PlanEnrollment.Status.ACTIVE},
        )
        self.client.post(
            f"/cartera/empresas/{self.business.pk}/polizas/nueva/",
            {
                "member": other_member.pk,
                "plan": self.plan.pk,
                "start_date": "2027-03-01",
            },
        )

        invited = self.client.post(f"{second_url}invitar/", follow=True)

        self.assertContains(invited, "Invitación enviada")
        self.assertEqual(len(mail.outbox), 1)
        proof = re.search(r"Código: (\S+)", str(mail.outbox[0].body))
        if proof is None:
            self.fail("El correo no incluyó un código de activación.")
        self.client.logout()
        activated = self.client.post(
            reverse("account-activate"),
            {
                "token": proof.group(1),
                "password1": "correct horse battery staple",
                "password2": "correct horse battery staple",
            },
            follow=True,
        )

        self.assertContains(activated, "Plan Familiar", count=2)
        self.assertContains(activated, "Activa")
        self.assertContains(activated, "Cancelada")
        self.assertNotContains(activated, "Otro Afiliado")
        self.member.refresh_from_db()
        self.assertEqual(self.member.account_id, int(self.client.session["_auth_user_id"]))
        self.assertEqual(self.member.country_code, "MX")
        self.assertEqual(self.member.gender, Member.Gender.FEMALE)
        self.assertEqual(self.member.phone, "+52 55 1111")
        self.assertEqual(self.member.attribution_source, "Carga inicial")
        self.assertFalse(self.member.do_not_contact)

    def test_other_reseller_cannot_view_or_add_beneficiaries_to_a_poliza(self) -> None:
        self.client.force_login(self.author)
        created = self.client.post(
            f"/cartera/empresas/{self.business.pk}/polizas/nueva/",
            {
                "member": self.member.pk,
                "plan": self.plan.pk,
                "start_date": "2027-01-31",
            },
            follow=True,
        )
        enrollment_url = created.redirect_chain[0][0]
        other_reseller = Reseller.objects.create(name="Socio Ajeno")
        other_admin = User.objects.create_user(
            email="other-admin@example.test",
            email_verified_at=timezone.now(),
        )
        create_reseller_scope(user=other_admin, reseller=other_reseller)
        self.client.force_login(other_admin)

        detail = self.client.get(enrollment_url)
        added = self.client.post(
            f"{enrollment_url}beneficiarios/nuevo/",
            {
                "full_name": "Persona Protegida",
                "relationship": "Hija",
                "country_code": "MX",
                "gender": Beneficiary.Gender.FEMALE,
            },
        )

        self.assertEqual(detail.status_code, 404)
        self.assertEqual(added.status_code, 404)
        self.assertFalse(Beneficiary.objects.exists())
