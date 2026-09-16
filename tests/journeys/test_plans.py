from datetime import date, timedelta

import pytest
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from catalog.models import Plan
from catalog.services import (
    DraftTerms,
    ServiceTerms,
    create_draft,
    create_plan,
    publish_draft,
    update_coverage_notes,
)
from organizations.models import AssistanceProvider, Reseller
from tests.builders import (
    create_business,
    create_provider_assignment,
    create_provider_scope,
    create_reseller_scope,
    create_tenant_scope,
)


@pytest.mark.journey
class PlanJourneyTests(TestCase):
    def setUp(self) -> None:
        self.reseller = Reseller.objects.create(name="Socio Norte")
        self.provider = AssistanceProvider.objects.create(name="Asistencia Norte")
        self.author = User.objects.create_user(
            email="author@example.test", email_verified_at=timezone.now()
        )
        self.reviewer = User.objects.create_user(
            email="reviewer@example.test", email_verified_at=timezone.now()
        )
        create_reseller_scope(user=self.author, reseller=self.reseller)
        create_reseller_scope(user=self.reviewer, reseller=self.reseller)
        self.draft_data = {
            "effective_from": "2026-10-01",
            "effective_until": "2027-10-01",
            "duration_months": "12",
            "coverage_terms": "Cobertura familiar.",
            "services-TOTAL_FORMS": "2",
            "services-INITIAL_FORMS": "0",
            "services-0-name": "Consulta médica",
            "services-0-coverage_terms": "Orientación telefónica.",
            "services-0-service_channels": ["online", "call_center"],
            "services-0-limit_text": "Sin límite durante la vigencia.",
            "services-1-name": "Ambulancia",
            "services-1-coverage_terms": "Traslado local.",
            "services-1-service_channels": ["call_center"],
            "services-1-limit_text": "",
        }

    def test_reseller_drafts_and_another_administrator_publishes_in_spanish(self) -> None:
        self.client.force_login(self.author)
        self.assertContains(self.client.get("/cartera/"), 'href="/planes/"')
        create = self.client.get("/planes/nuevo/")
        self.assertContains(create, "nuevo Plan")
        self.assertNotContains(create, 'name="internal_amount"')
        created = self.client.post(
            "/planes/nuevo/",
            {
                "reseller": self.reseller.pk,
                "provider": self.provider.pk,
                "name": "Plan Familiar",
                "auto_renew_enabled": "on",
            },
            follow=True,
        )
        self.assertEqual(len(created.redirect_chain), 1)
        plan_url = created.redirect_chain[0][0]
        self.assertContains(created, "Plan Familiar")
        self.assertContains(created, "Asistencia Norte")
        self.assertContains(created, "Renovación automática: habilitada")
        draft = self.client.post(f"{plan_url}versiones/nueva/", self.draft_data, follow=True)
        self.assertEqual(len(draft.redirect_chain), 1)
        version_url = draft.redirect_chain[0][0]
        self.assertContains(draft, "Borrador")
        self.assertContains(draft, "Consulta médica")
        self.assertContains(draft, "En línea")
        self.assertContains(draft, "Centro de atención telefónica")
        self.assertContains(draft, "Sin límite durante la vigencia.")
        self.assertContains(draft, "Otra persona autorizada")
        self.assertEqual(self.client.post(f"{version_url}publicar/").status_code, 403)
        self.client.force_login(self.reviewer)
        review = self.client.get(version_url)
        self.assertContains(review, "Publicar versión")
        published = self.client.post(f"{version_url}publicar/", follow=True)
        self.assertRedirects(published, version_url)
        self.assertContains(published, "Publicada")
        self.assertNotContains(published, "Publicar versión")
        self.assertNotContains(published, "Editar borrador")
        self.assertContains(published, "Orientación telefónica.")
        self.client.force_login(self.author)
        rejected = self.client.post(f"{version_url}editar/", self.draft_data)
        self.assertContains(rejected, "inmutables")

    def test_operator_manages_internal_pricing_and_publishes_without_admin_bypasses(self) -> None:
        operator = User.objects.create_superuser(email="operator@example.test")
        self.client.force_login(operator)
        admin_list = self.client.get(reverse("admin:catalog_plan_changelist"))
        self.assertContains(admin_list, 'href="/planes/"')
        created = self.client.post(
            "/planes/nuevo/",
            {
                "reseller": self.reseller.pk,
                "provider": self.provider.pk,
                "name": "Plan Privado",
                "internal_amount": "1987.65",
                "currency": "USD",
            },
            follow=True,
        )
        plan_url = created.redirect_chain[0][0]
        self.assertContains(created, "Importe interno")
        self.assertContains(created, "1987")
        self.assertContains(created, "USD")
        self.client.force_login(self.author)
        for url in ("/planes/", plan_url, f"{plan_url}editar/"):
            page = self.client.get(url)
            for private in ("internal_amount", "1987", "USD", "Importe interno"):
                self.assertNotContains(page, private)
        renamed = self.client.post(f"{plan_url}editar/", {"name": "Plan Renombrado"}, follow=True)
        self.assertContains(renamed, "Plan Renombrado")
        draft = self.client.post(f"{plan_url}versiones/nueva/", self.draft_data, follow=True)
        version_url = draft.redirect_chain[0][0]
        self.client.force_login(operator)
        self.assertContains(self.client.get(plan_url), "1987")
        published = self.client.post(f"{version_url}publicar/", follow=True)
        self.assertContains(published, "Publicada")
        version_id = int(version_url.strip("/").split("/")[-1])
        admin_edit = reverse("admin:catalog_planversion_change", args=[version_id])
        detail = self.client.get(admin_edit)
        self.assertNotContains(detail, 'name="_save"')
        self.assertEqual(self.client.post(admin_edit, {"duration_months": "1"}).status_code, 403)
        self.assertContains(self.client.get(version_url), "12 meses calendario")
        evidence = self.client.get(reverse("admin:audit_auditevent_changelist"))
        self.assertContains(evidence, "plan.published")
        self.assertTrue(AuditEvent.objects.filter(action="plan.rejected", actor=operator).exists())

    def test_reseller_updates_servicing_and_presentation_without_changing_published_terms(
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
            terms=DraftTerms(
                date(2026, 10, 1),
                date(2027, 10, 1),
                12,
                "Cobertura familiar.",
                (
                    ServiceTerms(
                        "Consulta médica",
                        "Orientación telefónica.",
                        ("online", "call_center"),
                        "Sin límite durante la vigencia.",
                    ),
                ),
            ),
        )
        publish_draft(actor=self.reviewer, version_id=version.pk)
        coverage = version.services.get()
        manage_url = f"/planes/coberturas/{coverage.pk}/gestionar/"
        self.client.force_login(self.author)

        page = self.client.get(manage_url)
        self.assertContains(page, "Notas internas de atención")
        self.assertContains(page, "Visible para Afiliados")
        invalid = self.client.post(
            manage_url,
            {
                "internal_notes": "Despachar con Central Norte.",
                "public_description": "Atención desde cualquier lugar.",
                "marketing_text": "Tu salud, siempre cerca.",
                "image_reference": "data:image/png;base64,private",
                "presentation_visible": "on",
            },
        )
        self.assertContains(invalid, "referencia de imagen")
        saved = self.client.post(
            manage_url,
            {
                "internal_notes": "Despachar con Central Norte.",
                "public_description": "Atención desde cualquier lugar.",
                "marketing_text": "Tu salud, siempre cerca.",
                "image_reference": "catalog/coverage-images/consulta.webp",
                "presentation_visible": "on",
            },
            follow=True,
        )
        self.assertContains(saved, "Atención desde cualquier lugar.")
        self.assertContains(saved, "Tu salud, siempre cerca.")
        self.assertNotContains(saved, "Despachar con Central Norte.")
        coverage.refresh_from_db()
        self.assertEqual(coverage.coverage_terms, "Orientación telefónica.")
        self.assertEqual(coverage.service_channels, ["online", "call_center"])
        self.assertEqual(coverage.limit_text, "Sin límite durante la vigencia.")
        self.assertEqual(coverage.internal_notes, "Despachar con Central Norte.")
        self.assertEqual(coverage.image_reference, "catalog/coverage-images/consulta.webp")
        evidence = AuditEvent.objects.filter(
            action__in=(
                "plan.coverage_notes_updated",
                "plan.coverage_presentation_updated",
            )
        )
        self.assertEqual(evidence.count(), 2)
        self.assertNotIn("Central Norte", str(list(evidence.values_list("changes", flat=True))))
        self.assertNotIn("Tu salud", str(list(evidence.values_list("changes", flat=True))))

    def test_cross_portfolio_and_forged_privileged_requests_leave_safe_evidence(self) -> None:
        plan = create_plan(
            actor=self.author,
            reseller_id=self.reseller.pk,
            provider_id=self.provider.pk,
            name="Plan Familiar",
        )
        version = create_draft(
            actor=self.author,
            plan_id=plan.pk,
            terms=DraftTerms(
                date(2026, 10, 1),
                date(2027, 10, 1),
                12,
                "Cobertura.",
                (ServiceTerms("Consulta", "Orientación."),),
            ),
        )
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
        plan_url = plan.get_absolute_url()
        version_url = version.get_absolute_url()
        self.client.force_login(outsider)
        self.assertNotContains(self.client.get("/planes/"), "Plan Familiar")
        for url in (
            plan_url,
            f"{plan_url}editar/",
            f"{plan_url}versiones/nueva/",
            version_url,
            f"{version_url}editar/",
        ):
            self.assertEqual(self.client.get(url).status_code, 404)
        for url in (
            f"{plan_url}editar/",
            f"{plan_url}versiones/nueva/",
            f"{version_url}editar/",
            f"{version_url}publicar/",
        ):
            self.assertEqual(self.client.post(url, self.draft_data).status_code, 404)
        self.client.force_login(self.author)
        for url, field in (
            (f"{plan_url}editar/", "provider"),
            (f"{plan_url}editar/", "reseller"),
            (f"{plan_url}editar/", "internal_amount"),
            ("/planes/nuevo/", "currency"),
            (f"{version_url}editar/", "author"),
            (f"{version_url}publicar/", "published_by"),
        ):
            self.assertEqual(
                self.client.post(url, {field: "sensitive-attack-value"}).status_code, 403
            )
        events = AuditEvent.objects.filter(action="plan.rejected")
        self.assertEqual(events.count(), 10)
        self.assertNotIn(
            "sensitive-attack-value", str(list(events.values_list("changes", flat=True)))
        )
        self.assertContains(self.client.get(plan_url), "Asistencia Norte")

    def test_provider_employee_sees_internal_notes_only_in_an_eligible_servicing_context(
        self,
    ) -> None:
        business = create_business(name="Empresa Norte", reseller=self.reseller)
        assignment = create_provider_assignment(business=business, provider=self.provider)
        provider_employee = User.objects.create_user(
            email="provider@example.test", email_verified_at=timezone.now()
        )
        create_provider_scope(
            user=provider_employee,
            provider_assignment=assignment,
        )
        plan = create_plan(
            actor=self.author,
            reseller_id=self.reseller.pk,
            provider_id=self.provider.pk,
            name="Plan Familiar",
        )
        today = timezone.localdate()
        version = create_draft(
            actor=self.author,
            plan_id=plan.pk,
            terms=DraftTerms(
                today - timedelta(days=1),
                today + timedelta(days=365),
                12,
                "Cobertura familiar.",
                (
                    ServiceTerms(
                        "Consulta médica",
                        "Orientación telefónica.",
                        ("online", "call_center"),
                    ),
                ),
            ),
        )
        publish_draft(actor=self.reviewer, version_id=version.pk)
        coverage = version.services.get()
        update_coverage_notes(
            actor=self.author,
            service_id=coverage.pk,
            internal_notes="Llamar a Central Norte y citar el convenio 42.",
        )
        servicing_url = f"/planes/atencion/empresas/{business.pk}/coberturas/{coverage.pk}/"

        self.client.force_login(provider_employee)
        page = self.client.get(servicing_url)
        self.assertContains(page, "Consulta médica")
        self.assertContains(page, "Orientación telefónica.")
        self.assertContains(page, "Llamar a Central Norte y citar el convenio 42.")
        outsider = User.objects.create_user(
            email="outsider-provider@example.test", email_verified_at=timezone.now()
        )
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(servicing_url).status_code, 404)
        assignment.is_active = False
        assignment.save(update_fields=["is_active"])
        self.client.force_login(provider_employee)
        self.assertEqual(self.client.get(servicing_url).status_code, 404)

    def test_cross_reseller_creation_rejected_by_form_is_still_audited(self) -> None:
        other = Reseller.objects.create(name="Socio Sur")
        self.client.force_login(self.author)
        rejected = self.client.post(
            "/planes/nuevo/",
            {
                "reseller": other.pk,
                "provider": self.provider.pk,
                "name": "Sensitive submitted value",
            },
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertContains(rejected, "errorlist")
        self.assertNotContains(self.client.get("/planes/"), "Sensitive submitted value")
        event = AuditEvent.objects.get(action="plan.rejected", actor=self.author)
        self.assertEqual(event.changes, {"operation": "request", "reason": "permission_denied"})
        self.assertNotIn("Sensitive", str(event.changes))
        operator = User.objects.create_superuser(email="operator@example.test")
        self.client.force_login(operator)
        self.assertNotContains(self.client.get("/planes/"), "Sensitive submitted value")

    def test_draft_form_supports_editing_deleting_and_adding_services_without_javascript(
        self,
    ) -> None:
        self.client.force_login(self.author)
        created = self.client.post(
            "/planes/nuevo/",
            {
                "name": "Plan Familiar",
                "reseller": self.reseller.pk,
                "provider": self.provider.pk,
            },
            follow=True,
        )
        plan_url = created.redirect_chain[0][0]
        self.assertContains(self.client.get(f"{plan_url}versiones/nueva/"), "Agregar otro servicio")
        expanded = self.client.post(
            f"{plan_url}versiones/nueva/", {**self.draft_data, "add_service": "1"}
        )
        self.assertContains(expanded, 'name="services-2-name"')
        self.assertNotContains(self.client.get(plan_url), "Versión 1")
        draft = self.client.post(f"{plan_url}versiones/nueva/", self.draft_data, follow=True)
        version_url = draft.redirect_chain[0][0]
        self.assertContains(self.client.get(f"{version_url}editar/"), "Consulta médica")
        edited_data = {
            **self.draft_data,
            "services-INITIAL_FORMS": "2",
            "services-0-name": "Consulta nueva",
            "services-1-DELETE": "on",
            "duration_months": "6",
        }
        edited = self.client.post(f"{version_url}editar/", edited_data, follow=True)
        self.assertRedirects(edited, version_url)
        self.assertContains(edited, "Consulta nueva")
        self.assertNotContains(edited, "Ambulancia")
        self.assertContains(edited, "6 meses calendario")
        invalid_data = {**self.draft_data, "effective_until": "2026-09-01"}
        invalid = self.client.post(f"{plan_url}versiones/nueva/", invalid_data)
        self.assertEqual(invalid.status_code, 200)
        self.assertContains(invalid, "errorlist")
        self.assertNotContains(self.client.get(plan_url), "Versión 2")
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(f"{version_url}editar/").status_code, 403)
        self.assertEqual(self.client.post(f"{version_url}editar/", edited_data).status_code, 403)

    def test_publication_requires_post_and_csrf_and_revocation_blocks_existing_sessions(
        self,
    ) -> None:
        self.client.force_login(self.author)
        plan = create_plan(
            actor=self.author,
            reseller_id=self.reseller.pk,
            provider_id=self.provider.pk,
            name="Plan Familiar",
        )
        draft = self.client.post(
            f"{plan.get_absolute_url()}versiones/nueva/", self.draft_data, follow=True
        )
        version_url = draft.redirect_chain[0][0]
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(f"{version_url}publicar/").status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.reviewer)
        self.assertEqual(csrf_client.post(f"{version_url}publicar/").status_code, 403)
        csrf_client.get(version_url)
        published = csrf_client.post(
            f"{version_url}publicar/",
            {"csrfmiddlewaretoken": csrf_client.cookies["csrftoken"].value},
            follow=True,
        )
        self.assertContains(published, "Publicada")
        duplicate = self.client.post(f"{version_url}publicar/", follow=True)
        self.assertContains(duplicate, "inmutables")
        self.reviewer.scoped_assignments.update(revoked_at=timezone.now())
        self.assertEqual(self.client.get("/planes/").status_code, 403)
        self.assertEqual(self.client.get(version_url).status_code, 404)
        self.assertEqual(self.client.post(f"{version_url}publicar/").status_code, 404)
        self.assertEqual(self.client.post("/planes/nuevo/", {}).status_code, 403)
        self.assertEqual(Client().get("/planes/").status_code, 302)

    def test_catalog_and_history_are_paginated_and_foreign_ids_do_not_expand_scope(self) -> None:
        self.client.force_login(self.author)
        for index in range(21):
            create_plan(
                actor=self.author,
                reseller_id=self.reseller.pk,
                provider_id=self.provider.pk,
                name=f"Plan {index:02d}",
            )
        first = self.client.get("/planes/", {"reseller": "999999"})
        self.assertContains(first, "Plan 00")
        self.assertNotContains(first, "Plan 20")
        self.assertContains(first, "Página 1 de 2")
        self.assertContains(self.client.get("/planes/?page=2"), "Plan 20")
        plan = create_plan(
            actor=self.author,
            reseller_id=self.reseller.pk,
            provider_id=self.provider.pk,
            name="Plan Histórico",
        )
        for _ in range(21):
            create_draft(
                actor=self.author,
                plan_id=plan.pk,
                terms=DraftTerms(
                    date(2026, 10, 1),
                    date(2027, 10, 1),
                    12,
                    "Cobertura.",
                    (ServiceTerms("Consulta", "Orientación."),),
                ),
            )
        history = self.client.get(plan.get_absolute_url())
        self.assertContains(history, "Versión 21</a>")
        self.assertNotContains(history, "Versión 1</a>")
        self.assertContains(history, "Página 1 de 2")
        self.assertContains(self.client.get(f"{plan.get_absolute_url()}?page=2"), "Versión 1</a>")

    def test_reseller_switches_plan_to_a_same_portfolio_business_allowlist(self) -> None:
        included = create_business(name="Empresa Incluida", reseller=self.reseller)
        create_business(name="Empresa Excluida", reseller=self.reseller)
        other_reseller = Reseller.objects.create(name="Socio Sur")
        foreign = create_business(name="Empresa Ajena", reseller=other_reseller)
        plan = create_plan(
            actor=self.author,
            reseller_id=self.reseller.pk,
            provider_id=self.provider.pk,
            name="Plan Familiar",
        )
        self.client.force_login(self.author)

        page = self.client.get(f"{plan.get_absolute_url()}disponibilidad/")
        self.assertContains(page, "Todas las empresas")
        self.assertContains(page, "Empresa Incluida")
        self.assertContains(page, "Empresa Excluida")
        self.assertNotContains(page, "Empresa Ajena")
        saved = self.client.post(
            f"{plan.get_absolute_url()}disponibilidad/",
            {
                "availability": Plan.Availability.SELECTED_BUSINESSES,
                "businesses": [included.pk],
            },
            follow=True,
        )
        self.assertRedirects(saved, plan.get_absolute_url())
        self.assertContains(saved, "Empresas seleccionadas")
        self.assertContains(saved, "Empresa Incluida")
        self.assertNotContains(saved, "Empresa Excluida")
        plan.refresh_from_db()
        self.assertEqual(plan.availability, Plan.Availability.SELECTED_BUSINESSES)
        self.assertQuerySetEqual(plan.selected_businesses.all(), [included])
        rejected = self.client.post(
            f"{plan.get_absolute_url()}disponibilidad/",
            {
                "availability": Plan.Availability.SELECTED_BUSINESSES,
                "businesses": [foreign.pk],
            },
        )
        self.assertContains(rejected, "Seleccione una opción válida")
        self.assertQuerySetEqual(plan.selected_businesses.all(), [included])
