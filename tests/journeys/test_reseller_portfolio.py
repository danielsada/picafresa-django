import pytest
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import GovernmentIdentifier, User
from accounts.services import add_government_identifier
from audit.models import AuditEvent
from organizations.models import AssistanceProvider, Reseller
from tests.builders import (
    create_business,
    create_provider_assignment,
    create_provider_scope,
    create_reseller_scope,
    create_tenant_scope,
)


@pytest.mark.journey
class ResellerPortfolioJourneyTests(TestCase):
    def setUp(self) -> None:
        self.north = Reseller.objects.create(name="Socio Norte")
        self.south = Reseller.objects.create(name="Socio Sur")
        self.business = create_business(name="Empresa Gemela", reseller=self.north)
        self.foreign_business = create_business(name="Empresa Gemela", reseller=self.south)
        self.provider = AssistanceProvider.objects.create(
            name="Asistencia Compartida",
            contact_name="Mesa de ayuda",
            contact_email="ayuda@example.com",
            contact_phone="+52 55 5555 0101",
            service_instructions="Llama y menciona tu Póliza.",
        )
        self.relationship = create_provider_assignment(
            business=self.business, provider=self.provider
        )
        self.foreign_relationship = create_provider_assignment(
            business=self.foreign_business, provider=self.provider
        )
        self.user = User.objects.create_user(
            email="reseller@example.com",
            password="portfolio test password",
            email_verified_at=timezone.now(),
        )
        self.scope = create_reseller_scope(user=self.user, reseller=self.north)

    def test_reseller_signs_in_to_only_active_assigned_portfolio_not_admin(self) -> None:
        inactive = create_business(name="Empresa Inactiva", reseller=self.north)
        inactive.is_active = False
        inactive.save()
        deleted = create_business(name="Empresa Eliminada", reseller=self.north)
        deleted.deleted_at = timezone.now()
        deleted.save()
        create_provider_scope(user=self.user, provider_assignment=self.foreign_relationship)
        create_tenant_scope(user=self.user, business=self.foreign_business)

        response = self.client.post(
            reverse("landing"),
            {"username": self.user.email, "password": "portfolio test password"},
            follow=True,
        )

        self.assertRedirects(response, "/cartera/")
        self.assertContains(response, "Mi cartera")
        self.assertContains(response, "Socio Norte")
        self.assertContains(response, "Empresa Gemela")
        for hidden in ("Socio Sur", "Empresa Inactiva", "Empresa Eliminada"):
            self.assertNotContains(response, hidden)
        self.assertNotContains(response, f"/cartera/empresas/{self.foreign_business.pk}/")
        admin_response = self.client.get(reverse("admin:index"))
        self.assertEqual(admin_response.status_code, 302)

    def test_reseller_can_edit_business_name_and_timezone_with_audit_evidence(self) -> None:
        self.client.force_login(self.user)
        detail_url = f"/cartera/empresas/{self.business.pk}/"
        portfolio = self.client.get("/cartera/")
        self.assertContains(portfolio, f'href="{detail_url}"')
        detail = self.client.get(detail_url)
        self.assertContains(detail, "Empresa Gemela")
        self.assertContains(detail, "Asistencia Compartida")

        response = self.client.post(
            f"{detail_url}editar/",
            {"name": "Empresa Renombrada", "timezone": "America/Tijuana"},
            follow=True,
        )

        self.assertRedirects(response, detail_url)
        self.assertContains(response, "Empresa Renombrada")
        self.assertContains(response, "America/Tijuana")
        self.assertContains(response, "Cambios guardados.")
        self.assertContains(self.client.get("/cartera/"), "Empresa Renombrada")
        operator = User.objects.create_superuser(email="operator@example.com")
        self.client.force_login(operator)
        audit = self.client.get(reverse("admin:audit_auditevent_changelist"))
        self.assertContains(audit, "organization.updated")
        self.assertContains(audit, self.user.email)

    def test_reseller_edits_only_business_specific_provider_contacts(self) -> None:
        self.client.force_login(self.user)
        detail_url = f"/cartera/empresas/{self.business.pk}/"
        edit_url = f"{detail_url}proveedores/{self.relationship.pk}/editar/"
        self.assertContains(self.client.get(detail_url), f'href="{edit_url}"')
        form = self.client.get(edit_url)
        self.assertContains(form, "Asistencia Compartida")
        self.assertContains(form, "Mesa de ayuda")

        response = self.client.post(
            edit_url,
            {
                "contact_name_override": "Línea Norte",
                "contact_email_override": "norte@example.com",
                "contact_phone_override": "+52 55 5555 0202",
                "service_instructions_override": "Marca la opción dos.",
            },
            follow=True,
        )

        self.assertRedirects(response, detail_url)
        for expected in (
            "Línea Norte",
            "norte@example.com",
            "+52 55 5555 0202",
            "Marca la opción dos.",
        ):
            self.assertContains(response, expected)
        south_user = User.objects.create_user(email="south@example.com")
        create_reseller_scope(user=south_user, reseller=self.south)
        self.client.force_login(south_user)
        other = self.client.get(f"/cartera/empresas/{self.foreign_business.pk}/")
        self.assertContains(other, "Mesa de ayuda")
        self.assertNotContains(other, "Línea Norte")
        self.client.force_login(self.user)
        cleared = self.client.post(
            edit_url,
            {
                "contact_name_override": "",
                "contact_email_override": "",
                "contact_phone_override": "",
                "service_instructions_override": "",
            },
            follow=True,
        )
        self.assertContains(cleared, "Mesa de ayuda")
        self.assertNotContains(cleared, "Línea Norte")

    def test_invalid_business_changes_show_errors_without_changing_saved_details(self) -> None:
        create_business(name="Nombre Ocupado", reseller=self.north)
        self.client.force_login(self.user)
        detail_url = f"/cartera/empresas/{self.business.pk}/"
        for name, timezone_name, error in (
            ("", "America/Mexico_City", "Este campo es obligatorio."),
            ("Nombre Ocupado", "America/Mexico_City", "ya existe"),
            ("Cambio Inválido", "Mexico/Not_A_Zone", "Escribe una zona horaria IANA válida."),
            ("Cambio Inválido", "/etc/passwd", "Escribe una zona horaria IANA válida."),
            ("Cambio Inválido", "../Mexico_City", "Escribe una zona horaria IANA válida."),
        ):
            with self.subTest(name=name, timezone=timezone_name):
                response = self.client.post(
                    f"{detail_url}editar/", {"name": name, "timezone": timezone_name}
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(error.lower(), response.content.decode().lower())
                detail = self.client.get(detail_url)
                self.assertContains(detail, "Empresa Gemela")
                self.assertContains(detail, "America/Mexico_City")
                self.assertNotContains(detail, "Cambio Inválido")

    def test_business_and_provider_pages_are_limited_to_twenty_scoped_records(self) -> None:
        self.client.force_login(self.user)
        for index in range(21):
            create_business(name=f"Sucursal {index:02d}", reseller=self.north)
            provider = AssistanceProvider.objects.create(name=f"Proveedor {index:02d}")
            create_provider_assignment(business=self.business, provider=provider)
        for url, prefix, initial_name in (
            ("/cartera/", "Sucursal", "Empresa Gemela"),
            (f"/cartera/empresas/{self.business.pk}/", "Proveedor", "Asistencia Compartida"),
        ):
            with self.subTest(url=url):
                first_names = (initial_name, *(f"{prefix} {index:02d}" for index in range(19)))
                second_names = (f"{prefix} 19", f"{prefix} 20")
                first = self.client.get(url)
                for name in first_names:
                    self.assertContains(first, name)
                for name in second_names:
                    self.assertNotContains(first, name)
                self.assertContains(first, "Página 1 de 2")
                self.assertContains(first, 'href="?page=2"')
                second = self.client.get(url, {"page": "2", "reseller": str(self.south.pk)})
                for name in second_names:
                    self.assertContains(second, name)
                for name in first_names:
                    self.assertNotContains(second, name)
                self.assertContains(second, 'href="?page=1"')
                self.assertNotContains(second, "Socio Sur")
                malformed = self.client.get(url, {"page": "invalid"})
                self.assertContains(malformed, "Página 1 de 2")
                beyond = self.client.get(url, {"page": "99999"})
                self.assertContains(beyond, "Página 2 de 2")

    def test_direct_urls_and_mismatched_relationships_cannot_cross_portfolios(self) -> None:
        self.client.force_login(self.user)
        other_business = create_business(name="Otra Empresa Norte", reseller=self.north)
        foreign_detail = f"/cartera/empresas/{self.foreign_business.pk}/"
        urls = (
            foreign_detail,
            f"{foreign_detail}editar/",
            f"{foreign_detail}proveedores/{self.foreign_relationship.pk}/editar/",
            f"/cartera/empresas/{self.business.pk}/proveedores/"
            f"{self.foreign_relationship.pk}/editar/",
            f"/cartera/empresas/{other_business.pk}/proveedores/{self.relationship.pk}/editar/",
            "/cartera/empresas/999999/editar/",
        )
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 404)
                self.assertNotContains(response, "Empresa Gemela", status_code=404)
                response = self.client.post(
                    url,
                    {
                        "name": "Intrusión",
                        "timezone": "America/Tijuana",
                        "contact_name_override": "Intrusión",
                    },
                )
                self.assertIn(response.status_code, (404, 405))
        south_user = User.objects.create_user(email="south@example.com")
        create_reseller_scope(user=south_user, reseller=self.south)
        self.client.force_login(south_user)
        unchanged = self.client.get(foreign_detail)
        self.assertContains(unchanged, "Empresa Gemela")
        self.assertContains(unchanged, "Mesa de ayuda")
        self.assertNotContains(unchanged, "Intrusión")

    def test_forged_fields_cannot_reassign_business_or_global_provider(self) -> None:
        unrelated = AssistanceProvider.objects.create(name="Proveedor Ajeno")
        self.client.force_login(self.user)
        detail_url = f"/cartera/empresas/{self.business.pk}/"
        response = self.client.post(
            f"{detail_url}editar/",
            {
                "name": "Nombre Permitido",
                "timezone": "America/Mexico_City",
                "reseller": str(self.south.pk),
                "is_active": "",
                "deleted_at": "2026-01-01T00:00:00Z",
                "id": str(self.foreign_business.pk),
            },
            follow=True,
        )
        self.assertContains(response, "Nombre Permitido")
        self.assertContains(response, "Socio Norte")
        response = self.client.post(
            f"{detail_url}proveedores/{self.relationship.pk}/editar/",
            {
                "contact_name_override": "Contacto Permitido",
                "business": str(self.foreign_business.pk),
                "provider": str(unrelated.pk),
                "name": "Nombre Global Prohibido",
                "contact_name": "Contacto Global Prohibido",
                "is_active": "",
                "deleted_at": "2026-01-01T00:00:00Z",
            },
            follow=True,
        )
        self.assertContains(response, "Contacto Permitido")
        self.assertContains(response, "Asistencia Compartida")
        self.assertContains(response, "Relación activa")
        for hidden in ("Socio Sur", "Proveedor Ajeno", "Global Prohibido"):
            self.assertNotContains(response, hidden)
        south_user = User.objects.create_user(email="south@example.com")
        create_reseller_scope(user=south_user, reseller=self.south)
        self.client.force_login(south_user)
        other = self.client.get(f"/cartera/empresas/{self.foreign_business.pk}/")
        self.assertContains(other, "Empresa Gemela")
        self.assertContains(other, "Asistencia Compartida")
        self.assertContains(other, "Mesa de ayuda")
        self.assertNotContains(other, "Contacto Permitido")

    def test_provider_and_tenant_roles_do_not_grant_portfolio_administration(self) -> None:
        for role in ("member", "provider", "tenant"):
            with self.subTest(role=role):
                user = User.objects.create_user(email=f"{role}@example.com")
                if role == "provider":
                    create_provider_scope(user=user, provider_assignment=self.relationship)
                elif role == "tenant":
                    create_tenant_scope(user=user, business=self.business)
                self.client.force_login(user)
                self.assertEqual(self.client.get("/cartera/").status_code, 403)
                detail_url = f"/cartera/empresas/{self.business.pk}/"
                self.assertEqual(self.client.get(detail_url).status_code, 404)
                for url in (
                    f"{detail_url}editar/",
                    f"{detail_url}proveedores/{self.relationship.pk}/editar/",
                ):
                    self.assertEqual(self.client.get(url).status_code, 404)
                    self.assertEqual(self.client.post(url, {"name": "Intrusión"}).status_code, 404)
                self.assertNotContains(self.client.get(reverse("account-home")), "Mi cartera")

    def test_revoking_scope_after_opening_form_blocks_both_mutations(self) -> None:
        self.client.force_login(self.user)
        detail_url = f"/cartera/empresas/{self.business.pk}/"
        edit_urls = (
            f"{detail_url}editar/",
            f"{detail_url}proveedores/{self.relationship.pk}/editar/",
        )
        for url in edit_urls:
            self.assertEqual(self.client.get(url).status_code, 200)
        self.scope.revoked_at = timezone.now()
        self.scope.save()
        self.assertEqual(self.client.get("/cartera/").status_code, 403)
        for url in edit_urls:
            response = self.client.post(
                url,
                {
                    "name": "Intrusión",
                    "timezone": "America/Mexico_City",
                    "contact_name_override": "Intrusión",
                },
            )
            self.assertEqual(response.status_code, 404)

    def test_inactive_or_deleted_organizations_cannot_be_read_or_edited(self) -> None:
        self.client.force_login(self.user)
        detail_url = f"/cartera/empresas/{self.business.pk}/"
        provider_url = f"{detail_url}proveedores/{self.relationship.pk}/editar/"
        for organization in (self.north, self.business, self.provider, self.relationship):
            for field, value in (("is_active", False), ("deleted_at", timezone.now())):
                if organization == self.relationship and field == "is_active":
                    continue  # Inactive contracts remain inspectable until ticket 09.
                with self.subTest(organization=type(organization).__name__, field=field):
                    setattr(organization, field, value)
                    organization.save()
                    self.assertEqual(self.client.get(provider_url).status_code, 404)
                    self.assertEqual(self.client.post(provider_url, {}).status_code, 404)
                    if organization in (self.north, self.business):
                        self.assertEqual(self.client.get(detail_url).status_code, 404)
                        self.assertEqual(
                            self.client.post(
                                f"{detail_url}editar/",
                                {"name": "Intrusión", "timezone": "America/Tijuana"},
                            ).status_code,
                            404,
                        )
                    else:
                        detail = self.client.get(detail_url)
                        self.assertNotContains(detail, "Asistencia Compartida")
                    setattr(organization, field, True if field == "is_active" else None)
                    organization.save()

    def test_staff_flag_does_not_send_reseller_to_platform_admin(self) -> None:
        self.user.is_staff = True
        self.user.save()
        response = self.client.post(
            reverse("landing"),
            {
                "username": self.user.email,
                "password": "portfolio test password",
                "next": "https://untrusted.example/",
            },
        )
        self.assertRedirects(response, "/cartera/")
        self.assertContains(self.client.get(reverse("account-home")), 'href="/cartera/"')

    def test_login_preserves_safe_portfolio_destination(self) -> None:
        detail_url = f"/cartera/empresas/{self.business.pk}/"
        self.assertRedirects(
            self.client.get(detail_url), f"/?next={detail_url}", fetch_redirect_response=False
        )
        response = self.client.post(
            reverse("landing"),
            {
                "username": self.user.email,
                "password": "portfolio test password",
                "next": detail_url,
            },
        )
        self.assertRedirects(response, detail_url)

    def test_portfolio_forms_require_csrf_and_get_requests_do_not_mutate(self) -> None:
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        detail_url = f"/cartera/empresas/{self.business.pk}/"
        for url in (
            f"{detail_url}editar/",
            f"{detail_url}proveedores/{self.relationship.pk}/editar/",
        ):
            with self.subTest(url=url):
                page = client.get(url, {"name": "Intrusión"})
                self.assertContains(page, 'name="csrfmiddlewaretoken"')
                self.assertIn("no-store", page.headers["Cache-Control"])
                self.assertEqual(client.post(url, {"name": "Intrusión"}).status_code, 403)
                self.assertEqual(
                    client.delete(
                        url, headers={"X-CSRFToken": client.cookies["csrftoken"].value}
                    ).status_code,
                    405,
                )
        self.assertContains(client.get(detail_url), "Empresa Gemela")
        self.assertEqual(
            client.post(
                "/cartera/", {}, headers={"X-CSRFToken": client.cookies["csrftoken"].value}
            ).status_code,
            405,
        )

    def test_empty_portfolio_and_inactive_contract_have_explicit_states(self) -> None:
        self.client.force_login(self.user)
        self.relationship.is_active = False
        self.relationship.save()
        detail = self.client.get(f"/cartera/empresas/{self.business.pk}/")
        self.assertContains(detail, "Relación inactiva")
        self.business.is_active = False
        self.business.save()
        self.assertContains(self.client.get("/cartera/"), "No hay empresas activas en tu cartera.")

    def test_reseller_creates_and_deactivates_a_provider_contract(self) -> None:
        available = AssistanceProvider.objects.create(name="Asistencia Nueva")
        self.client.force_login(self.user)
        detail_url = f"/cartera/empresas/{self.business.pk}/"
        form = self.client.get(f"{detail_url}proveedores/nuevo/")
        self.assertContains(form, "Asistencia Nueva")
        created = self.client.post(
            f"{detail_url}proveedores/nuevo/",
            {"provider": available.pk},
            follow=True,
        )
        self.assertRedirects(created, detail_url)
        self.assertContains(created, "Asistencia Nueva")
        contract = self.business.provider_assignments.get(provider=available)
        deactivated = self.client.post(
            f"{detail_url}proveedores/{contract.pk}/desactivar/",
            follow=True,
        )
        self.assertRedirects(deactivated, detail_url)
        self.assertContains(deactivated, "Contrato inactivo")
        contract.refresh_from_db()
        self.assertFalse(contract.is_active)
        provider_employee = User.objects.create_user(
            email="provider.employee@example.com",
            email_verified_at=timezone.now(),
        )
        create_provider_scope(user=provider_employee, provider_assignment=self.relationship)
        self.client.force_login(provider_employee)
        self.assertEqual(self.client.get("/cartera/").status_code, 403)
        self.assertEqual(
            self.client.get(f"{detail_url}proveedores/nuevo/").status_code,
            404,
        )

    def test_rendered_pages_exclude_privileged_fields_and_unrelated_data(self) -> None:
        add_government_identifier(self.user, GovernmentIdentifier.Kind.MX_RFC, "GODE561231GR8")
        AuditEvent.objects.create(
            actor=self.user,
            action="test.private",
            object_type="business",
            object_reference=str(self.business.pk),
            changes={"raw_payload": "PAYLOAD-PRIVADO", "internal_price": "987654.32"},
        )
        self.foreign_relationship.contact_name_override = "Contacto Ajeno"
        self.foreign_relationship.save()
        self.client.force_login(self.user)
        detail_url = f"/cartera/empresas/{self.business.pk}/"
        for url in (
            "/cartera/",
            detail_url,
            f"{detail_url}editar/",
            f"{detail_url}proveedores/{self.relationship.pk}/editar/",
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                for hidden in (
                    "PAYLOAD-PRIVADO",
                    "987654.32",
                    "internal_price",
                    "raw_payload",
                    "government_identifier",
                    "GODE561231GR8",
                    "Socio Sur",
                    "Contacto Ajeno",
                    'href="/admin/',
                    'name="reseller"',
                    'name="business"',
                    'name="provider"',
                    'name="is_active"',
                    'name="deleted_at"',
                ):
                    self.assertNotContains(response, hidden)

    def test_provider_validation_and_escaped_contact_rendering(self) -> None:
        self.client.force_login(self.user)
        detail_url = f"/cartera/empresas/{self.business.pk}/"
        edit_url = f"{detail_url}proveedores/{self.relationship.pk}/editar/"
        response = self.client.post(edit_url, {"contact_email_override": "not-an-email"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Introduzca una dirección de correo electrónico válida.")
        self.assertContains(self.client.get(detail_url), "ayuda@example.com")
        response = self.client.post(
            edit_url,
            {"service_instructions_override": "<script>alert('test')</script>"},
            follow=True,
        )
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>")

    def test_multiple_reseller_assignments_include_only_live_portfolios(self) -> None:
        self.client.force_login(self.user)
        south_scope = create_reseller_scope(user=self.user, reseller=self.south)
        response = self.client.get("/cartera/")
        self.assertContains(response, "Socio Norte")
        self.assertContains(response, "Socio Sur")
        south_scope.revoked_at = timezone.now()
        south_scope.save()
        response = self.client.get("/cartera/")
        self.assertContains(response, "Socio Norte")
        self.assertNotContains(response, "Socio Sur")
        self.north.is_active = False
        self.north.save()
        self.assertContains(self.client.get("/cartera/"), "Acceso no permitido", status_code=403)

    def test_inactive_account_loses_portfolio_access(self) -> None:
        self.client.force_login(self.user)
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.client.get("/cartera/").status_code, 302)

    def test_saving_unchanged_business_is_valid(self) -> None:
        self.client.force_login(self.user)
        detail_url = f"/cartera/empresas/{self.business.pk}/"
        response = self.client.post(
            f"{detail_url}editar/",
            {"name": "Empresa Gemela", "timezone": "America/Mexico_City"},
            follow=True,
        )
        self.assertRedirects(response, detail_url)
        self.assertContains(response, "Empresa Gemela")
