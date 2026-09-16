from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from catalog.services import DraftTerms, ServiceTerms, create_draft, create_plan, publish_draft
from enrollments.models import Member, PlanEnrollment
from enrollments.services import (
    EnrollmentTerms,
    RenewalGenerationUnavailable,
    UnavailableRenewalGenerator,
    create_enrollment,
    is_renewal_eligible,
    renew_enrollment,
    transition_enrollment,
)
from organizations.models import AssistanceProvider, Reseller
from tests.builders import (
    create_business,
    create_provider_assignment,
    create_provider_scope,
    create_reseller_scope,
)


class EnrollmentServiceTests(TestCase):
    def setUp(self) -> None:
        self.reseller = Reseller.objects.create(name="Socio Norte")
        self.business = create_business(name="Empresa Norte", reseller=self.reseller)
        self.provider = AssistanceProvider.objects.create(
            name="Asistencia Norte",
            contact_name="Mesa de atención",
            contact_email="ayuda@example.test",
            contact_phone="+52 55 0101",
            service_instructions="Llama con tu número de Póliza.",
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

    def publish_version(
        self,
        *,
        effective_from: date = date(2026, 1, 1),
        effective_until: date = date(2030, 1, 1),
        duration_months: int = 1,
    ) -> None:
        version = create_draft(
            actor=self.author,
            plan_id=self.plan.pk,
            terms=DraftTerms(
                effective_from,
                effective_until,
                duration_months,
                "Cobertura familiar.",
                (ServiceTerms("Consulta", "Orientación médica."),),
            ),
        )
        publish_draft(actor=self.reviewer, version_id=version.pk)

    def test_creation_uses_calendar_months_and_snapshots_provider_contact(self) -> None:
        self.publish_version()

        enrollment = create_enrollment(
            actor=self.author,
            terms=EnrollmentTerms(
                member_id=self.member.pk,
                plan_id=self.plan.pk,
                start_date=date(2027, 1, 31),
            ),
        )

        self.assertEqual(enrollment.end_date, date(2027, 2, 28))
        self.assertEqual(enrollment.duration_months, 1)
        self.assertEqual(enrollment.provider_contact_name, "Mesa de atención")
        self.assertEqual(enrollment.provider_contact_email, "ayuda@example.test")
        self.assertEqual(enrollment.provider_contact_phone, "+52 55 0101")
        self.assertEqual(
            enrollment.provider_service_instructions,
            "Llama con tu número de Póliza.",
        )

    def test_calendar_month_calculation_handles_leap_years_and_exclusive_end(self) -> None:
        self.publish_version(
            effective_from=date(2024, 1, 1),
            effective_until=date(2026, 1, 1),
            duration_months=12,
        )

        enrollment = create_enrollment(
            actor=self.author,
            terms=EnrollmentTerms(
                member_id=self.member.pk,
                plan_id=self.plan.pk,
                start_date=date(2024, 2, 29),
            ),
        )

        self.assertEqual(enrollment.end_date, date(2025, 2, 28))
        self.assertTrue(enrollment.covers(date(2024, 2, 29)))
        self.assertTrue(enrollment.covers(date(2025, 2, 27)))
        self.assertFalse(enrollment.covers(date(2025, 2, 28)))

    def test_terminal_enrollment_cannot_reactivate(self) -> None:
        self.publish_version()
        enrollment = create_enrollment(
            actor=self.author,
            terms=EnrollmentTerms(
                member_id=self.member.pk,
                plan_id=self.plan.pk,
                start_date=date(2027, 1, 1),
            ),
        )
        transition_enrollment(
            actor=self.author,
            enrollment_id=enrollment.pk,
            target_status=PlanEnrollment.Status.CANCELLED,
        )

        with self.assertRaisesMessage(ValidationError, "transición"):
            transition_enrollment(
                actor=self.author,
                enrollment_id=enrollment.pk,
                target_status=PlanEnrollment.Status.ACTIVE,
            )

    def test_renewal_uses_latest_version_and_links_without_rewriting_prior_term(self) -> None:
        self.publish_version(duration_months=1)
        original = create_enrollment(
            actor=self.author,
            terms=EnrollmentTerms(
                member_id=self.member.pk,
                plan_id=self.plan.pk,
                start_date=date(2027, 1, 1),
            ),
        )
        original_version_id = original.plan_version_id
        self.plan.auto_renew_enabled = True
        self.plan.save(update_fields=["auto_renew_enabled"])
        self.publish_version(
            effective_from=date(2027, 2, 1),
            effective_until=date(2031, 1, 1),
            duration_months=2,
        )

        renewal = renew_enrollment(actor=self.author, enrollment_id=original.pk)

        original.refresh_from_db()
        self.assertEqual(original.plan_version_id, original_version_id)
        self.assertEqual(renewal.preceding_enrollment, original)
        self.assertEqual(renewal.plan_version.number, 2)
        self.assertEqual(renewal.start_date, original.end_date)
        self.assertEqual(renewal.end_date, date(2027, 4, 1))

    def test_renewal_eligibility_requires_both_flags(self) -> None:
        for plan_allows, member_allows, expected in (
            (False, False, False),
            (False, True, False),
            (True, False, False),
            (True, True, True),
        ):
            with self.subTest(plan_allows=plan_allows, member_allows=member_allows):
                self.plan.auto_renew_enabled = plan_allows
                self.member.auto_renew_allowed = member_allows
                self.assertEqual(
                    is_renewal_eligible(plan=self.plan, member=self.member),
                    expected,
                )

    def test_explicit_end_override_requires_reason_and_records_audit_evidence(self) -> None:
        self.publish_version()
        terms = EnrollmentTerms(
            member_id=self.member.pk,
            plan_id=self.plan.pk,
            start_date=date(2027, 1, 31),
            explicit_end_date=date(2027, 3, 15),
        )
        with self.assertRaisesMessage(ValidationError, "motivo"):
            create_enrollment(actor=self.author, terms=terms)

        enrollment = create_enrollment(
            actor=self.author,
            terms=EnrollmentTerms(
                member_id=self.member.pk,
                plan_id=self.plan.pk,
                start_date=date(2027, 1, 31),
                explicit_end_date=date(2027, 3, 15),
                override_reason="Acuerdo contractual documentado.",
            ),
        )

        event = AuditEvent.objects.get(action="enrollment.eligibility_overridden")
        self.assertEqual(enrollment.end_date, date(2027, 3, 15))
        self.assertEqual(event.changes["reason"], "Acuerdo contractual documentado.")

    def test_provider_employee_cannot_apply_eligibility_override(self) -> None:
        self.publish_version()
        provider_employee = User.objects.create_user(email="provider@example.test")
        create_provider_scope(
            user=provider_employee,
            provider_assignment=self.contract,
        )
        self.contract.is_active = False
        self.contract.save(update_fields=["is_active"])

        with self.assertRaises(PermissionDenied):
            create_enrollment(
                actor=provider_employee,
                terms=EnrollmentTerms(
                    member_id=self.member.pk,
                    plan_id=self.plan.pk,
                    start_date=date(2027, 1, 1),
                    allow_eligibility_override=True,
                    override_reason="Solicitud del Proveedor.",
                ),
            )

    def test_database_rejects_term_mutation_and_invalid_direct_transition(self) -> None:
        self.publish_version()
        enrollment = create_enrollment(
            actor=self.author,
            terms=EnrollmentTerms(
                member_id=self.member.pk,
                plan_id=self.plan.pk,
                start_date=date(2027, 1, 1),
            ),
        )

        with self.assertRaises(DatabaseError), transaction.atomic():
            PlanEnrollment.objects.filter(pk=enrollment.pk).update(end_date=date(2027, 5, 1))
        with self.assertRaises(DatabaseError), transaction.atomic():
            PlanEnrollment.objects.filter(pk=enrollment.pk).update(
                status=PlanEnrollment.Status.EXPIRED
            )
        with self.assertRaises(DatabaseError), transaction.atomic():
            PlanEnrollment.objects.create(
                member=self.member,
                business=self.business,
                plan_version=enrollment.plan_version,
                start_date=date(2027, 2, 1),
                end_date=date(2027, 4, 1),
                duration_months=2,
                created_by=self.author,
            )

    def test_automatic_renewal_generator_fails_explicitly_while_unavailable(self) -> None:
        with self.assertRaisesMessage(RenewalGenerationUnavailable, "no existe"):
            UnavailableRenewalGenerator().generate_due_renewals(as_of=date(2027, 1, 1))
