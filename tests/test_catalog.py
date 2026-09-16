from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from decimal import Decimal
from threading import Barrier

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from catalog.models import Plan, PlanBusinessAvailability, PlanService, PlanVersion
from catalog.selectors import visible_plans
from catalog.services import (
    CoveragePresentation,
    DraftTerms,
    ServiceTerms,
    create_draft,
    create_plan,
    member_coverage_contents,
    publish_draft,
    resolve_available_plan_version,
    set_plan_availability,
    update_coverage_notes,
    update_coverage_presentation,
    update_draft,
    update_plan,
)
from organizations.models import AssistanceProvider, Business, Reseller
from tests.builders import (
    create_business,
    create_provider_assignment,
    create_provider_scope,
    create_reseller_scope,
    create_tenant_scope,
)


class PlanServiceTests(TestCase):
    def setUp(self) -> None:
        self.reseller = Reseller.objects.create(name="Socio Norte")
        self.provider = AssistanceProvider.objects.create(name="Asistencia Norte")
        self.author = User.objects.create_user(email="author@example.test")
        self.reviewer = User.objects.create_user(email="reviewer@example.test")
        create_reseller_scope(user=self.author, reseller=self.reseller)
        create_reseller_scope(user=self.reviewer, reseller=self.reseller)
        self.terms = DraftTerms(
            effective_from=date(2026, 10, 1),
            effective_until=date(2027, 10, 1),
            duration_months=12,
            coverage_terms="Asistencia familiar durante la vigencia.",
            services=(
                ServiceTerms(name="Consulta médica", coverage_terms="Orientación telefónica."),
            ),
        )

    def test_reseller_prepares_owned_plan_and_versioned_member_services(self) -> None:
        terms = replace(
            self.terms,
            services=(
                ServiceTerms(
                    name="Ambulancia",
                    coverage_terms="Traslado local.",
                    service_channels=("call_center",),
                    limit_text="Hasta dos eventos durante la vigencia.",
                ),
                ServiceTerms(
                    name="Consulta médica",
                    coverage_terms="Orientación remota.",
                    service_channels=("online", "call_center"),
                ),
            ),
        )
        plan = create_plan(
            actor=self.author,
            reseller_id=self.reseller.pk,
            provider_id=self.provider.pk,
            name="Plan Familiar",
        )
        version = create_draft(actor=self.author, plan_id=plan.pk, terms=terms)

        saved = visible_plans(self.author).get(pk=plan.pk)
        self.assertEqual(saved.reseller_id, self.reseller.pk)
        self.assertEqual(saved.provider_id, self.provider.pk)
        self.assertIsNone(saved.internal_amount)
        self.assertEqual(version.number, 1)
        self.assertEqual(version.status, "draft")
        self.assertEqual(version.author_id, self.author.pk)
        self.assertEqual(version.effective_from, date(2026, 10, 1))
        self.assertEqual(version.effective_until, date(2027, 10, 1))
        self.assertEqual(version.duration_months, 12)
        self.assertEqual(version.coverage_terms, "Asistencia familiar durante la vigencia.")
        self.assertEqual(
            list(
                version.services.values_list(
                    "position", "name", "coverage_terms", "service_channels", "limit_text"
                )
            ),
            [
                (
                    1,
                    "Ambulancia",
                    "Traslado local.",
                    ["call_center"],
                    "Hasta dos eventos durante la vigencia.",
                ),
                (
                    2,
                    "Consulta médica",
                    "Orientación remota.",
                    ["online", "call_center"],
                    "",
                ),
            ],
        )

    def test_publication_requires_another_authorized_actor_and_keeps_safe_evidence(self) -> None:
        plan = create_plan(
            actor=self.author,
            reseller_id=self.reseller.pk,
            provider_id=self.provider.pk,
            name="Plan Familiar",
        )
        version = create_draft(actor=self.author, plan_id=plan.pk, terms=self.terms)
        with self.assertRaises(PermissionDenied):
            publish_draft(actor=self.author, version_id=version.pk)
        rejected = AuditEvent.objects.get(action="plan.rejected")
        self.assertEqual(rejected.actor_id, self.author.pk)
        self.assertEqual(rejected.object_reference, str(version.pk))
        self.assertEqual(rejected.changes, {"operation": "publish", "reason": "permission_denied"})

        published = publish_draft(actor=self.reviewer, version_id=version.pk)
        self.assertEqual(published.status, "published")
        self.assertEqual(published.author_id, self.author.pk)
        self.assertEqual(published.published_by_id, self.reviewer.pk)
        self.assertIsNotNone(published.published_at)
        evidence = AuditEvent.objects.get(action="plan.published")
        self.assertEqual(evidence.actor_id, self.reviewer.pk)
        self.assertEqual(evidence.active_scope_reference, str(self.reseller.pk))
        self.assertEqual(evidence.changes, {"number": 1})

    def test_authorized_operator_updates_internal_notes_after_publication_with_safe_evidence(
        self,
    ) -> None:
        plan = create_plan(
            actor=self.author,
            reseller_id=self.reseller.pk,
            provider_id=self.provider.pk,
            name="Plan Familiar",
        )
        version = create_draft(actor=self.author, plan_id=plan.pk, terms=self.terms)
        publish_draft(actor=self.reviewer, version_id=version.pk)
        coverage = version.services.get()

        updated = update_coverage_notes(
            actor=self.author,
            service_id=coverage.pk,
            internal_notes="Despachar con Central Norte al 55 0000 0000.",
        )

        self.assertEqual(updated.internal_notes, "Despachar con Central Norte al 55 0000 0000.")
        self.assertEqual(updated.name, "Consulta médica")
        self.assertEqual(updated.coverage_terms, "Orientación telefónica.")
        evidence = AuditEvent.objects.get(action="plan.coverage_notes_updated")
        self.assertEqual(evidence.changes, {"fields": ["internal_notes"]})
        self.assertNotIn("Central Norte", str(evidence.changes))

    def test_presentation_defaults_hidden_and_remains_mutable_after_publication(self) -> None:
        plan = create_plan(
            actor=self.author,
            reseller_id=self.reseller.pk,
            provider_id=self.provider.pk,
            name="Plan Familiar",
        )
        version = create_draft(actor=self.author, plan_id=plan.pk, terms=self.terms)
        publish_draft(actor=self.reviewer, version_id=version.pk)
        coverage = version.services.get()
        self.assertFalse(coverage.presentation_visible)

        updated = update_coverage_presentation(
            actor=self.author,
            service_id=coverage.pk,
            presentation=CoveragePresentation(
                public_description="Atención médica desde cualquier lugar.",
                marketing_text="Tu salud, siempre cerca.",
                visible=True,
            ),
        )

        self.assertEqual(updated.public_description, "Atención médica desde cualquier lugar.")
        self.assertEqual(updated.marketing_text, "Tu salud, siempre cerca.")
        self.assertTrue(updated.presentation_visible)
        self.assertEqual(updated.coverage_terms, "Orientación telefónica.")
        evidence = AuditEvent.objects.get(action="plan.coverage_presentation_updated")
        self.assertEqual(
            evidence.changes,
            {
                "fields": ["marketing_text", "presentation_visible", "public_description"],
                "visible": True,
            },
        )
        self.assertNotIn("Tu salud", str(evidence.changes))

    def test_member_coverage_projection_keeps_entitlements_independent_of_visibility(
        self,
    ) -> None:
        plan = create_plan(
            actor=self.author,
            reseller_id=self.reseller.pk,
            provider_id=self.provider.pk,
            name="Plan Familiar",
        )
        version = create_draft(
            actor=self.author,
            plan_id=plan.pk,
            terms=replace(
                self.terms,
                services=(
                    ServiceTerms("Ambulancia", "Traslado local.", ("call_center",)),
                    ServiceTerms("Consulta", "Orientación.", ("online",)),
                ),
            ),
        )
        ambulance, consultation = version.services.all()
        update_coverage_notes(
            actor=self.author,
            service_id=consultation.pk,
            internal_notes="Contacto interno confidencial.",
        )
        update_coverage_presentation(
            actor=self.author,
            service_id=consultation.pk,
            presentation=CoveragePresentation(
                public_description="Consulta desde casa.",
                marketing_text="Siempre cerca.",
                visible=True,
                image_reference="catalog/coverage-images/consulta.png",
            ),
        )

        contents = member_coverage_contents(version_id=version.pk)

        self.assertEqual([coverage.name for coverage in contents], ["Ambulancia", "Consulta"])
        self.assertEqual(contents[0].public_description, "")
        self.assertFalse(contents[0].presentation_visible)
        self.assertEqual(contents[1].public_description, "Consulta desde casa.")
        self.assertTrue(contents[1].presentation_visible)
        self.assertEqual(contents[1].coverage_terms, "Orientación.")
        self.assertEqual(contents[1].service_channels, ("online",))
        self.assertEqual(contents[1].image_reference, "catalog/coverage-images/consulta.png")
        self.assertFalse(hasattr(contents[1], "internal_notes"))
        self.assertEqual(ambulance.position, 1)

    def test_author_edits_only_drafts_and_new_versions_preserve_published_terms(self) -> None:
        plan = create_plan(
            actor=self.author,
            reseller_id=self.reseller.pk,
            provider_id=self.provider.pk,
            name="Plan Familiar",
        )
        first = create_draft(actor=self.author, plan_id=plan.pk, terms=self.terms)
        changed = replace(
            self.terms,
            duration_months=6,
            services=(ServiceTerms(name="Ambulancia", coverage_terms="Traslado local."),),
        )
        with self.assertRaises(PermissionDenied):
            update_draft(actor=self.reviewer, version_id=first.pk, terms=changed)
        edited = update_draft(actor=self.author, version_id=first.pk, terms=changed)
        self.assertEqual(edited.duration_months, 6)
        self.assertEqual(list(edited.services.values_list("name", flat=True)), ["Ambulancia"])
        publish_draft(actor=self.reviewer, version_id=first.pk)
        with self.assertRaises(ValidationError):
            update_draft(actor=self.author, version_id=first.pk, terms=self.terms)
        with self.assertRaises(ValidationError):
            publish_draft(actor=self.reviewer, version_id=first.pk)
        second = create_draft(actor=self.author, plan_id=plan.pk, terms=self.terms)
        self.assertEqual(second.number, 2)
        original = visible_plans(self.author).get(pk=plan.pk).versions.get(number=1)
        self.assertEqual(original.duration_months, 6)
        self.assertEqual(list(original.services.values_list("name", flat=True)), ["Ambulancia"])

    def test_provider_is_permanent_and_only_platform_operators_can_manage_pricing(self) -> None:
        operator = User.objects.create_superuser(email="operator@example.test")
        plan = create_plan(
            actor=operator,
            reseller_id=self.reseller.pk,
            provider_id=self.provider.pk,
            name="Plan Familiar",
            internal_amount=Decimal("1987.65"),
            currency="USD",
        )
        with self.assertRaises(PermissionDenied):
            update_plan(
                actor=self.author,
                plan_id=plan.pk,
                name=plan.name,
                provider_id=self.provider.pk,
                internal_amount=Decimal("1.00"),
                currency="MXN",
            )
        other = AssistanceProvider.objects.create(name="Otro Proveedor")
        with self.assertRaisesMessage(ValidationError, "nuevo Plan"):
            update_plan(
                actor=operator,
                plan_id=plan.pk,
                name=plan.name,
                provider_id=other.pk,
                internal_amount=None,
                currency="MXN",
            )
        updated = update_plan(
            actor=operator,
            plan_id=plan.pk,
            name="Plan Nuevo Nombre",
            provider_id=self.provider.pk,
            internal_amount=Decimal("2000.00"),
            currency="MXN",
        )
        self.assertEqual(updated.internal_amount, Decimal("2000.00"))
        self.assertEqual(updated.currency, "MXN")
        self.assertEqual(updated.provider_id, self.provider.pk)
        self.assertEqual(AuditEvent.objects.filter(action="plan.rejected").count(), 2)
        for event in AuditEvent.objects.filter(action__startswith="plan."):
            self.assertNotIn("2000", str(event.changes))
            self.assertNotIn("1987", str(event.changes))

    def test_published_terms_and_provider_resist_orm_bypasses(self) -> None:
        plan = create_plan(
            actor=self.author,
            reseller_id=self.reseller.pk,
            provider_id=self.provider.pk,
            name="Plan Familiar",
        )
        version = create_draft(actor=self.author, plan_id=plan.pk, terms=self.terms)
        publish_draft(actor=self.reviewer, version_id=version.pk)
        service = version.services.get()
        other = AssistanceProvider.objects.create(name="Otro Proveedor")
        draft = create_draft(actor=self.author, plan_id=plan.pk, terms=self.terms)
        draft_service = draft.services.get()
        mutations = (
            lambda: Plan.objects.filter(pk=plan.pk).update(provider=other),
            lambda: PlanVersion.objects.filter(pk=version.pk).update(duration_months=3),
            lambda: PlanVersion.objects.filter(pk=version.pk).update(status="draft"),
            lambda: PlanService.objects.filter(pk=service.pk).update(name="Cambio"),
            lambda: PlanService.objects.filter(pk=service.pk).update(position=2),
            lambda: PlanService.objects.filter(pk=service.pk).update(coverage_terms="Cambio"),
            lambda: PlanService.objects.filter(pk=service.pk).update(
                service_channels=["call_center"]
            ),
            lambda: PlanService.objects.filter(pk=service.pk).update(limit_text="Cambio"),
            lambda: PlanService.objects.filter(pk=service.pk).delete(),
            lambda: PlanService.objects.create(
                version=version, name="Extra", coverage_terms="Extra"
            ),
            lambda: PlanService.objects.filter(pk=service.pk).update(version=draft),
            lambda: PlanService.objects.filter(pk=draft_service.pk).update(version=version),
        )
        for mutate in mutations:
            with (
                self.subTest(mutation=mutate),
                self.assertRaises(DatabaseError),
                transaction.atomic(),
            ):
                mutate()
        version.duration_months = 3
        with self.assertRaises(DatabaseError), transaction.atomic():
            version.save()
        PlanService.objects.filter(pk=service.pk).update(
            internal_notes="Nueva instrucción.",
            public_description="Nueva presentación.",
            marketing_text="Nuevo mensaje.",
            image_reference="catalog/coverage-images/nueva.png",
            presentation_visible=True,
        )
        service.refresh_from_db()
        self.assertEqual(service.internal_notes, "Nueva instrucción.")
        self.assertTrue(service.presentation_visible)

    def test_out_of_scope_creation_is_rejected_and_audited_without_submitted_values(self) -> None:
        other = Reseller.objects.create(name="Socio Sur")
        with self.assertRaises(PermissionDenied):
            create_plan(
                actor=self.author,
                reseller_id=other.pk,
                provider_id=self.provider.pk,
                name="Private submitted contact",
            )
        event = AuditEvent.objects.get(action="plan.rejected")
        self.assertEqual(event.actor_id, self.author.pk)
        self.assertEqual(event.changes, {"operation": "create_plan", "reason": "permission_denied"})
        self.assertNotIn("Private", str(event.changes))
        self.assertFalse(visible_plans(self.author).exists())

    def test_invalid_draft_does_not_persist_any_version_or_partial_service_changes(self) -> None:
        plan = create_plan(
            actor=self.author,
            reseller_id=self.reseller.pk,
            provider_id=self.provider.pk,
            name="Plan Familiar",
        )
        invalid_terms = (
            replace(self.terms, duration_months=0),
            replace(self.terms, duration_months=-1),
            replace(self.terms, effective_until=self.terms.effective_from),
            replace(self.terms, coverage_terms=""),
            replace(self.terms, services=()),
            replace(self.terms, services=(*self.terms.services, ServiceTerms("", "Invalid"))),
        )
        for terms in invalid_terms:
            with self.subTest(terms=terms), self.assertRaises(ValidationError):
                create_draft(actor=self.author, plan_id=plan.pk, terms=terms)
        self.assertFalse(visible_plans(self.author).get(pk=plan.pk).versions.exists())
        self.assertEqual(AuditEvent.objects.filter(action="plan.rejected").count(), 6)
        version = create_draft(actor=self.author, plan_id=plan.pk, terms=self.terms)
        self.assertEqual(version.number, 1)
        with self.assertRaises(ValidationError):
            update_draft(actor=self.author, version_id=version.pk, terms=invalid_terms[-1])
        saved = visible_plans(self.author).get(pk=plan.pk).versions.get(pk=version.pk)
        self.assertEqual(list(saved.services.values_list("name", flat=True)), ["Consulta médica"])

    def test_service_channels_reject_empty_and_unsupported_values_in_services_and_database(
        self,
    ) -> None:
        plan = create_plan(
            actor=self.author,
            reseller_id=self.reseller.pk,
            provider_id=self.provider.pk,
            name="Plan Familiar",
        )
        for channels in ((), ("fax",)):
            with self.subTest(channels=channels), self.assertRaises(ValidationError):
                create_draft(
                    actor=self.author,
                    plan_id=plan.pk,
                    terms=replace(
                        self.terms,
                        services=(
                            ServiceTerms(
                                "Consulta",
                                "Orientación.",
                                channels,
                            ),
                        ),
                    ),
                )
        version = create_draft(actor=self.author, plan_id=plan.pk, terms=self.terms)
        coverage = version.services.get()
        for database_channels in ([], ["fax"]):
            with (
                self.subTest(channels=database_channels),
                self.assertRaises(DatabaseError),
                transaction.atomic(),
            ):
                PlanService.objects.filter(pk=coverage.pk).update(
                    service_channels=database_channels
                )

    def test_composable_non_reseller_roles_never_authorize_catalog_operations(self) -> None:
        plan = create_plan(
            actor=self.author,
            reseller_id=self.reseller.pk,
            provider_id=self.provider.pk,
            name="Plan Familiar",
        )
        version = create_draft(actor=self.author, plan_id=plan.pk, terms=self.terms)
        outsider = User.objects.create_user(email="outsider@example.test", is_staff=True)
        other = Reseller.objects.create(name="Socio Sur")
        create_reseller_scope(user=outsider, reseller=other)
        business = create_business(name="Empresa Norte", reseller=self.reseller)
        create_tenant_scope(user=outsider, business=business)
        create_provider_scope(
            user=outsider,
            provider_assignment=create_provider_assignment(
                business=business,
                provider=self.provider,
            ),
        )
        self.assertFalse(visible_plans(outsider).exists())
        operations = (
            lambda: create_draft(actor=outsider, plan_id=plan.pk, terms=self.terms),
            lambda: update_draft(actor=outsider, version_id=version.pk, terms=self.terms),
            lambda: publish_draft(actor=outsider, version_id=version.pk),
            lambda: update_plan(
                actor=outsider, plan_id=plan.pk, name="Intrusion", provider_id=self.provider.pk
            ),
            lambda: update_coverage_notes(
                actor=outsider,
                service_id=version.services.get().pk,
                internal_notes="Intrusión",
            ),
            lambda: update_coverage_presentation(
                actor=outsider,
                service_id=version.services.get().pk,
                presentation=CoveragePresentation("", "", True),
            ),
        )
        for operate in operations:
            with self.subTest(operation=operate), self.assertRaises(PermissionDenied):
                operate()
        self.assertEqual(AuditEvent.objects.filter(action="plan.rejected").count(), 6)

    def test_inactive_scopes_and_providers_block_changes_but_operators_retain_history(self) -> None:
        operator = User.objects.create_superuser(email="operator@example.test")
        plan = create_plan(
            actor=self.author,
            reseller_id=self.reseller.pk,
            provider_id=self.provider.pk,
            name="Plan Familiar",
        )
        version = create_draft(actor=self.author, plan_id=plan.pk, terms=self.terms)
        self.reseller.is_active = False
        self.reseller.save()
        self.assertFalse(visible_plans(self.author).exists())
        self.assertTrue(visible_plans(operator).filter(pk=plan.pk).exists())
        with self.assertRaises(PermissionDenied):
            publish_draft(actor=operator, version_id=version.pk)
        self.reseller.is_active = True
        self.reseller.save()
        self.provider.deleted_at = timezone.now()
        self.provider.save()
        with self.assertRaises(ValidationError):
            publish_draft(actor=self.reviewer, version_id=version.pk)
        with self.assertRaises(ValidationError):
            create_plan(
                actor=self.author,
                reseller_id=self.reseller.pk,
                provider_id=self.provider.pk,
                name="Invalid Provider",
            )
        self.reviewer.is_active = False
        self.reviewer.save()
        self.assertFalse(visible_plans(self.reviewer).exists())
        with self.assertRaises(PermissionDenied):
            publish_draft(actor=self.reviewer, version_id=version.pk)

    def test_platform_author_cannot_self_publish_and_reseller_cannot_set_creation_price(
        self,
    ) -> None:
        operator = User.objects.create_superuser(email="operator@example.test")
        with self.assertRaises(PermissionDenied):
            create_plan(
                actor=self.author,
                reseller_id=self.reseller.pk,
                provider_id=self.provider.pk,
                name="Plan Familiar",
                internal_amount=Decimal("42.00"),
            )
        plan = create_plan(
            actor=operator,
            reseller_id=self.reseller.pk,
            provider_id=self.provider.pk,
            name="Plan Familiar",
        )
        version = create_draft(actor=operator, plan_id=plan.pk, terms=self.terms)
        with self.assertRaises(PermissionDenied):
            publish_draft(actor=operator, version_id=version.pk)
        self.assertEqual(
            publish_draft(actor=self.author, version_id=version.pk).status, "published"
        )

    def test_availability_resolves_default_all_and_selected_businesses_with_active_contracts(
        self,
    ) -> None:
        first_business = create_business(name="Empresa Uno", reseller=self.reseller)
        second_business = create_business(name="Empresa Dos", reseller=self.reseller)
        first_contract = create_provider_assignment(business=first_business, provider=self.provider)
        create_provider_assignment(business=second_business, provider=self.provider)
        plan = create_plan(
            actor=self.author,
            reseller_id=self.reseller.pk,
            provider_id=self.provider.pk,
            name="Plan Familiar",
        )
        version = create_draft(actor=self.author, plan_id=plan.pk, terms=self.terms)
        publish_draft(actor=self.reviewer, version_id=version.pk)

        self.assertEqual(
            resolve_available_plan_version(
                business_id=first_business.pk,
                plan_id=plan.pk,
                on_date=date(2026, 10, 1),
            ),
            version,
        )
        set_plan_availability(
            actor=self.author,
            plan_id=plan.pk,
            availability=Plan.Availability.SELECTED_BUSINESSES,
            business_ids=(second_business.pk,),
        )
        self.assertIsNone(
            resolve_available_plan_version(
                business_id=first_business.pk,
                plan_id=plan.pk,
                on_date=date(2026, 10, 1),
            )
        )
        self.assertEqual(
            resolve_available_plan_version(
                business_id=second_business.pk,
                plan_id=plan.pk,
                on_date=date(2026, 10, 1),
            ),
            version,
        )
        first_contract.is_active = False
        first_contract.save(update_fields=["is_active"])
        set_plan_availability(
            actor=self.author,
            plan_id=plan.pk,
            availability=Plan.Availability.ALL_BUSINESSES,
            business_ids=(),
        )
        self.assertIsNone(
            resolve_available_plan_version(
                business_id=first_business.pk,
                plan_id=plan.pk,
                on_date=date(2026, 10, 1),
            )
        )

    def test_availability_rejects_cross_reseller_links_and_non_effective_versions(self) -> None:
        business = create_business(name="Empresa Norte", reseller=self.reseller)
        create_provider_assignment(business=business, provider=self.provider)
        other_reseller = Reseller.objects.create(name="Socio Sur")
        other_business = create_business(name="Empresa Sur", reseller=other_reseller)
        plan = create_plan(
            actor=self.author,
            reseller_id=self.reseller.pk,
            provider_id=self.provider.pk,
            name="Plan Familiar",
        )
        version = create_draft(actor=self.author, plan_id=plan.pk, terms=self.terms)

        self.assertIsNone(
            resolve_available_plan_version(
                business_id=business.pk,
                plan_id=plan.pk,
                on_date=date(2026, 10, 1),
            )
        )
        publish_draft(actor=self.reviewer, version_id=version.pk)
        self.assertIsNone(
            resolve_available_plan_version(
                business_id=business.pk,
                plan_id=plan.pk,
                on_date=date(2027, 10, 1),
            )
        )
        with self.assertRaises(ValidationError):
            set_plan_availability(
                actor=self.author,
                plan_id=plan.pk,
                availability=Plan.Availability.SELECTED_BUSINESSES,
                business_ids=(other_business.pk,),
            )
        with self.assertRaises(DatabaseError), transaction.atomic():
            PlanBusinessAvailability.objects.create(plan=plan, business=other_business)
        PlanBusinessAvailability.objects.create(plan=plan, business=business)
        with self.assertRaises(DatabaseError), transaction.atomic():
            Business.objects.filter(pk=business.pk).update(reseller=other_reseller)


class ConcurrentPlanServiceTests(TransactionTestCase):
    def test_parallel_drafts_have_distinct_numbers_and_publication_happens_only_once(self) -> None:
        reseller = Reseller.objects.create(name="Socio Norte")
        provider = AssistanceProvider.objects.create(name="Asistencia Norte")
        author = User.objects.create_user(email="author@example.test")
        reviewers = [
            User.objects.create_user(email=f"reviewer{index}@example.test") for index in range(2)
        ]
        for user in (author, *reviewers):
            create_reseller_scope(user=user, reseller=reseller)
        plan = create_plan(
            actor=author, reseller_id=reseller.pk, provider_id=provider.pk, name="Concurrent Plan"
        )
        terms = DraftTerms(
            date(2026, 10, 1),
            date(2027, 10, 1),
            12,
            "Cobertura.",
            (ServiceTerms("Consulta", "Orientación."),),
        )
        draft_barrier = Barrier(2)

        def draft_number() -> int:
            try:
                draft_barrier.wait(timeout=10)
                return create_draft(actor=author, plan_id=plan.pk, terms=terms).number
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(draft_number) for _ in range(2)]
            self.assertEqual(sorted(future.result(timeout=20) for future in futures), [1, 2])
        version = visible_plans(author).get(pk=plan.pk).versions.get(number=1)
        publish_barrier = Barrier(2)

        def publish(reviewer: User) -> str:
            try:
                publish_barrier.wait(timeout=10)
                try:
                    return publish_draft(actor=reviewer, version_id=version.pk).status
                except ValidationError:
                    return "rejected"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(publish, reviewers))
        self.assertCountEqual(results, ["published", "rejected"])
        self.assertEqual(AuditEvent.objects.filter(action="plan.published").count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action="plan.rejected").count(), 1)
