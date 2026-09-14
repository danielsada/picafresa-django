from django.test import SimpleTestCase
from django.urls import reverse


class LandingPageTests(SimpleTestCase):
    def test_visitor_can_open_spanish_sign_in_page_without_database(self) -> None:
        response = self.client.get(reverse("landing"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bienvenido a Picafresa")
        self.assertContains(response, "Iniciar sesión")
