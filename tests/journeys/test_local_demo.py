import json
import re
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, override_settings

from accounts.models import User
from organizations.models import AssistanceProvider, Reseller, ScopedAssignment


@pytest.mark.journey
class LocalDemoJourneyTests(TestCase):
    @override_settings(SETTINGS_MODULE="config.settings.local")
    def test_demo_accounts_sign_in_to_named_isolated_portfolios(self) -> None:
        output = StringIO()
        call_command("seed_local_demo", stdout=output)
        accounts = json.loads(output.getvalue())
        self.assertEqual(
            [account["email"] for account in accounts],
            [
                "demo.operador@example.test",
                "demo.archers@example.test",
                "demo.carlos@example.test",
                "demo.salubritas@example.test",
                "demo.pedro@example.test",
            ],
        )
        for account in accounts:
            with self.subTest(email=account["email"]):
                self.client.logout()
                response = self.client.post(
                    "/",
                    {"username": account["email"], "password": account["password"]},
                    follow=True,
                )
                if account["email"] == "demo.operador@example.test":
                    self.assertRedirects(response, "/admin/")
                else:
                    self.assertRedirects(response, "/cartera/")
                    self.assertContains(response, account["role"])
                    self.assertContains(response, "Página 1 de 2")
                    self.assertContains(self.client.get("/cartera/?page=2"), "Sucursal demo 21")
                    for other in (
                        "Archers",
                        "Carlos Asistencias",
                        "Salubritas SA de CV",
                        "Pedro Beneficios",
                    ):
                        if other != account["role"]:
                            self.assertNotContains(response, other)
                    if account["role"] == "Archers":
                        self.assertContains(response, "M21")
                        self.assertContains(response, "HUC")

    @override_settings(SETTINGS_MODULE="config.settings.local")
    def test_rerunning_demo_rotates_passwords_and_preserves_live_contact_edits(self) -> None:
        first_output = StringIO()
        call_command("seed_local_demo", stdout=first_output)
        archers = json.loads(first_output.getvalue())[1]
        response = self.client.post(
            "/",
            {"username": archers["email"], "password": archers["password"]},
            follow=True,
        )
        self.assertRedirects(response, "/cartera/")
        business_link = re.search(r'href="(/cartera/empresas/\d+/)"', response.content.decode())
        assert business_link is not None
        business_url = business_link.group(1)
        detail = self.client.get(business_url)
        self.assertContains(detail, "Asistencias Cuatro")
        self.assertContains(detail, "Asistencias MENOS")
        provider_link = re.search(
            r'href="(/cartera/empresas/\d+/proveedores/\d+/editar/)"', detail.content.decode()
        )
        assert provider_link is not None
        edit_url = provider_link.group(1)
        self.client.post(edit_url, {"contact_name_override": "Mi contacto de prueba"})
        self.client.post(
            f"{business_url}editar/",
            {"name": "Empresa renombrada durante la prueba", "timezone": "America/Tijuana"},
        )

        second_output = StringIO()
        call_command("seed_local_demo", stdout=second_output)
        second_accounts = json.loads(second_output.getvalue())
        self.assertTrue(all(account["password"] for account in second_accounts))
        second_archers = second_accounts[1]
        self.assertNotEqual(second_archers["password"], archers["password"])
        self.client.logout()
        response = self.client.post(
            "/",
            {"username": archers["email"], "password": archers["password"]},
            follow=True,
        )
        self.assertEqual(response.redirect_chain, [])
        response = self.client.post(
            "/",
            {"username": second_archers["email"], "password": second_archers["password"]},
            follow=True,
        )
        self.assertRedirects(response, "/cartera/")
        self.assertContains(response, "Página 1 de 2")
        self.assertContains(self.client.get(business_url), "Mi contacto de prueba")
        self.assertContains(self.client.get(business_url), "Empresa renombrada durante la prueba")
        self.assertNotContains(response, "HUC")

    @override_settings(SETTINGS_MODULE="config.settings.local")
    def test_seed_rejects_existing_cross_portfolio_permissions(self) -> None:
        user = User.objects.create_superuser(email="operator@example.test")
        self.client.force_login(user)
        first_output = StringIO()
        call_command("seed_local_demo", stdout=first_output)
        archers_user = User.objects.get(email="demo.archers@example.test")
        carlos = Reseller.objects.get(name="Carlos Asistencias")
        ScopedAssignment.objects.create(
            user=archers_user,
            role=ScopedAssignment.Role.RESELLER_ADMIN,
            reseller=carlos,
        )

        with self.assertRaisesMessage(CommandError, "otras organizaciones"):
            call_command("seed_local_demo", stdout=StringIO())

    @override_settings(SETTINGS_MODULE="config.settings.local")
    def test_rerun_preserves_renamed_organizations_and_revoked_permissions(self) -> None:
        output = StringIO()
        call_command("seed_local_demo", stdout=output)
        archers = json.loads(output.getvalue())[1]
        self.client.force_login(User.objects.get(email="demo.operador@example.test"))
        reseller = Reseller.objects.get(name="Archers")
        provider = AssistanceProvider.objects.get(name="Asistencias Cuatro")
        assignment = ScopedAssignment.objects.get(user__email=archers["email"])
        self.client.post(
            f"/admin/organizations/reseller/{reseller.pk}/change/",
            {"name": "Cartera Renombrada", "is_active": "on"},
        )
        self.client.post(
            f"/admin/organizations/assistanceprovider/{provider.pk}/change/",
            {"name": "Proveedor Renombrado", "is_active": "on"},
        )
        self.client.post(
            f"/admin/organizations/scopedassignment/{assignment.pk}/delete/",
            {"post": "yes"},
        )

        rerun_output = StringIO()
        call_command("seed_local_demo", stdout=rerun_output)
        rerun_accounts = json.loads(rerun_output.getvalue())
        operator = rerun_accounts[0]
        archers = rerun_accounts[1]
        self.client.logout()
        response = self.client.post(
            "/",
            {"username": operator["email"], "password": operator["password"]},
            follow=True,
        )
        self.assertRedirects(response, "/admin/")

        resellers = self.client.get("/admin/organizations/reseller/")
        self.assertContains(resellers, "Cartera Renombrada")
        self.assertNotContains(resellers, "Archers")
        providers = self.client.get("/admin/organizations/assistanceprovider/")
        self.assertContains(providers, "Proveedor Renombrado")
        self.assertNotContains(providers, "Asistencias Cuatro")
        self.client.logout()
        response = self.client.post(
            "/",
            {"username": archers["email"], "password": archers["password"]},
            follow=True,
        )
        self.assertRedirects(response, "/cuenta/")
        self.assertEqual(self.client.get("/cartera/").status_code, 403)

    @override_settings(SETTINGS_MODULE="config.settings.local")
    def test_conflicting_account_rolls_back_seed_without_revealing_credentials(self) -> None:
        operator = User.objects.create_superuser(email="existing.operator@example.test")
        User.objects.create_user(email="demo.pedro@example.test")
        output = StringIO()

        with self.assertRaisesMessage(CommandError, "otro estado o permisos"):
            call_command("seed_local_demo", stdout=output)

        self.assertEqual(output.getvalue(), "")
        self.client.force_login(operator)
        response = self.client.get("/admin/organizations/reseller/")
        for name in ("Archers", "Carlos Asistencias", "Salubritas SA de CV", "Pedro Beneficios"):
            self.assertNotContains(response, name)
        users = self.client.get("/admin/accounts/user/")
        self.assertContains(users, "demo.pedro@example.test")
        self.assertNotContains(users, "demo.operador@example.test")


class LocalDemoEnvironmentTests(SimpleTestCase):
    def test_seed_refuses_nonlocal_settings_before_accessing_database(self) -> None:
        for module in (
            "config.settings.staging",
            "config.settings.production",
            "config.settings.test",
        ):
            with (
                self.subTest(module=module),
                override_settings(SETTINGS_MODULE=module),
                self.assertRaisesMessage(CommandError, "solo se pueden crear"),
            ):
                call_command("seed_local_demo")
