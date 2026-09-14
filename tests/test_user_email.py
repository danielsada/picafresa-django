from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TransactionTestCase

from accounts.models import User


class UserEmailTests(TransactionTestCase):
    def test_email_is_normalized_and_unique_regardless_of_case(self) -> None:
        user = get_user_model().objects.create_user(
            email=" Member@Example.COM ",
            password="not-a-real-password",
        )

        self.assertEqual(user.email, "member@example.com")

        with self.assertRaises(IntegrityError):
            User.objects.create(email="MEMBER@example.com")
