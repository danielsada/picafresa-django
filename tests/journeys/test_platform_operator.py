import pytest
from django.test import TestCase
from django.urls import reverse

from accounts.models import User


@pytest.mark.journey
class PlatformOperatorJourneyTests(TestCase):
    def test_platform_operator_can_sign_in_and_enter_admin(self) -> None:
        password = "test-password"
        user = User.objects.create_superuser(
            email="operator@example.com",
            password=password,
        )

        sign_in_response = self.client.post(
            reverse("admin:login"),
            {
                "username": user.email,
                "password": password,
                "next": reverse("landing"),
            },
        )

        self.assertRedirects(
            sign_in_response,
            reverse("landing"),
            fetch_redirect_response=False,
        )

        landing_response = self.client.get(reverse("landing"))

        self.assertRedirects(
            landing_response,
            reverse("admin:index"),
            fetch_redirect_response=False,
        )
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)
