from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import User


class LandingPageTests(SimpleTestCase):
    def test_visitor_can_open_spanish_sign_in_page_without_database(self) -> None:
        response = self.client.get(reverse("landing"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bienvenido a Picafresa")
        self.assertContains(response, "Iniciar sesión")


class AuthenticatedLandingPageTests(TestCase):
    def test_authenticated_staff_user_is_redirected_to_admin(self) -> None:
        user = User.objects.create_superuser(
            email="admin@example.com",
            password="test-password",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("landing"))

        self.assertRedirects(
            response,
            reverse("admin:index"),
            fetch_redirect_response=False,
        )
