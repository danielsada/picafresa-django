from django.db import IntegrityError
from django.test import TransactionTestCase

from accounts.models import GovernmentIdentifier, User
from accounts.services import (
    InvalidGovernmentIdentifier,
    add_government_identifier,
    normalize_government_identifier,
)


class AccountIdentityTests(TransactionTestCase):
    def test_rfc_encoded_date_must_be_a_real_calendar_date(self) -> None:
        self.assertEqual(
            normalize_government_identifier(
                GovernmentIdentifier.Kind.MX_RFC,
                "GODE-000229-GR8",
            ),
            "GODE000229GR8",
        )

        for invalid_rfc in ("GODE-010229-GR8", "GODE-991332-GR8"):
            with (
                self.subTest(rfc=invalid_rfc),
                self.assertRaises(InvalidGovernmentIdentifier),
            ):
                normalize_government_identifier(
                    GovernmentIdentifier.Kind.MX_RFC,
                    invalid_rfc,
                )

    def test_inactive_account_keeps_email_and_rfc_uniqueness(self) -> None:
        inactive_user = User.objects.create_user(
            email="former.member@example.com",
            is_active=False,
        )
        add_government_identifier(
            inactive_user,
            GovernmentIdentifier.Kind.MX_RFC,
            "GODE-561231-GR8",
        )

        with self.assertRaises(IntegrityError):
            User.objects.create_user(
                email=" FORMER.MEMBER@EXAMPLE.COM ",
                is_active=False,
            )

        another_user = User.objects.create_user(
            email="another.member@example.com",
            is_active=False,
        )
        with self.assertRaises(IntegrityError):
            add_government_identifier(
                another_user,
                GovernmentIdentifier.Kind.MX_RFC,
                "gode561231gr8",
            )
