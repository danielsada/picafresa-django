import logging
import re
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import GovernmentIdentifier, User
from accounts.services import add_government_identifier, issue_activation


class MemberAccountJourneyTests(TestCase):
    def test_invited_member_activates_once_through_verified_email(self) -> None:
        user = User.objects.create_user(email=" Member@Example.COM ", is_active=False)
        issue_activation(user)
        proof = re.search(r"Código: (\S+)", str(mail.outbox[0].body))
        if proof is None:
            self.fail("El correo no incluyó un código de activación.")
        token = proof.group(1)

        response = self.client.post(
            reverse("account-activate"),
            {
                "token": token,
                "password1": "correct horse battery staple",
                "password2": "correct horse battery staple",
            },
        )

        self.assertRedirects(response, reverse("account-home"))
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertIsNotNone(user.email_verified_at)
        self.assertTrue(user.check_password("correct horse battery staple"))
        duplicate = self.client.post(
            reverse("account-activate"),
            {
                "token": token,
                "password1": "another correct horse battery staple",
                "password2": "another correct horse battery staple",
            },
        )
        self.assertEqual(duplicate.status_code, 400)

    def test_member_signs_in_by_verified_email_or_rfc_without_raw_rfc_storage(self) -> None:
        email_user = User.objects.create_user(
            email="email.member@example.com",
            password="correct horse battery staple",
            email_verified_at=timezone.now(),
        )
        rfc_user = User.objects.create_user(
            email="rfc.member@example.com",
            password="another correct horse battery staple",
            email_verified_at=timezone.now(),
        )
        add_government_identifier(rfc_user, GovernmentIdentifier.Kind.MX_RFC, " GODE-561231-GR8 ")

        response = self.client.post(
            reverse("landing"),
            {
                "username": " EMAIL.MEMBER@EXAMPLE.COM ",
                "password": "correct horse battery staple",
            },
        )
        self.assertRedirects(
            response,
            reverse("account-home"),
            fetch_redirect_response=False,
        )
        self.client.logout()

        response = self.client.post(
            reverse("landing"),
            {
                "username": "gode561231gr8",
                "password": "another correct horse battery staple",
            },
        )
        self.assertRedirects(
            response,
            reverse("account-home"),
            fetch_redirect_response=False,
        )
        self.assertEqual(int(self.client.session["_auth_user_id"]), rfc_user.pk)
        identity = GovernmentIdentifier.objects.get(user=rfc_user)
        self.assertNotIn("GODE561231GR8", identity.lookup_digest)
        self.assertNotIn("GODE-561231-GR8", identity.lookup_digest)
        self.assertNotEqual(email_user.pk, rfc_user.pk)

    def test_verified_email_can_reset_password_without_putting_proof_in_url(self) -> None:
        user = User.objects.create_user(
            email="recover.member@example.com",
            password="old correct horse battery staple",
            email_verified_at=timezone.now(),
        )
        unverified = User.objects.create_user(
            email="unverified.member@example.com",
            password="old correct horse battery staple",
        )

        response = self.client.post(
            reverse("password-reset"),
            {"email": " RECOVER.MEMBER@EXAMPLE.COM "},
        )

        self.assertRedirects(response, reverse("password-reset-sent"))
        old_proof = re.search(r"Código: (\S+)", str(mail.outbox[0].body))
        if old_proof is None:
            self.fail("El correo no incluyó un código de recuperación.")
        old_token = old_proof.group(1)
        self.client.post(
            reverse("password-reset"),
            {"email": "recover.member@example.com"},
        )
        proof = re.search(r"Código: (\S+)", str(mail.outbox[1].body))
        if proof is None:
            self.fail("El correo no incluyó un código de recuperación.")
        token = proof.group(1)
        self.assertNotIn(token, response.headers["Location"])

        response = self.client.post(
            reverse("password-reset-confirm"),
            {
                "token": token,
                "password1": "new correct horse battery staple",
                "password2": "new correct horse battery staple",
            },
        )
        self.assertRedirects(response, reverse("landing"))
        user.refresh_from_db()
        self.assertTrue(user.check_password("new correct horse battery staple"))
        stale = self.client.post(
            reverse("password-reset-confirm"),
            {
                "token": old_token,
                "password1": "stale correct horse battery staple",
                "password2": "stale correct horse battery staple",
            },
        )
        self.assertEqual(stale.status_code, 400)

        self.client.post(
            reverse("password-reset"),
            {"email": unverified.email},
        )
        self.client.post(
            reverse("password-reset"),
            {"email": "unknown.member@example.com"},
        )
        self.assertEqual(len(mail.outbox), 2)

    def test_email_change_reauthenticates_verifies_notifies_and_revokes_sessions(self) -> None:
        user = User.objects.create_user(
            email="old.member@example.com",
            password="correct horse battery staple",
            email_verified_at=timezone.now(),
        )
        self.client.login(
            username=user.email,
            password="correct horse battery staple",
        )
        other_session = Client()
        other_session.login(
            username=user.email,
            password="correct horse battery staple",
        )

        rejected = self.client.post(
            reverse("email-change"),
            {
                "current_password": "wrong password",
                "new_email": "new.member@example.com",
            },
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

        response = self.client.post(
            reverse("email-change"),
            {
                "current_password": "correct horse battery staple",
                "new_email": " NEW.MEMBER@EXAMPLE.COM ",
            },
        )
        self.assertRedirects(response, reverse("email-change-sent"))
        self.assertEqual(mail.outbox[0].to, ["new.member@example.com"])
        proof = re.search(r"Código: (\S+)", str(mail.outbox[0].body))
        if proof is None:
            self.fail("El correo no incluyó un código de verificación.")
        token = proof.group(1)

        response = self.client.post(
            reverse("email-change-confirm"),
            {"token": token},
        )

        self.assertRedirects(response, reverse("landing"))
        user.refresh_from_db()
        self.assertEqual(user.email, "new.member@example.com")
        self.assertEqual(mail.outbox[1].to, ["old.member@example.com"])
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotIn("_auth_user_id", other_session.session)

    def test_expired_and_invalid_proofs_are_rejected_without_sensitive_logs(self) -> None:
        user = User.objects.create_user(email="invited.member@example.com", is_active=False)
        issued_at = timezone.now()
        with patch("accounts.services.timezone.now", return_value=issued_at):
            issue_activation(user)
        proof = re.search(r"Código: (\S+)", str(mail.outbox[0].body))
        if proof is None:
            self.fail("El correo no incluyó un código de activación.")
        token = proof.group(1)
        password = "correct horse battery staple"
        raw_rfc = "GODE-561231-GR8"

        with (
            patch(
                "accounts.services.timezone.now",
                return_value=issued_at + timedelta(hours=25),
            ),
            self.assertLogs(level=logging.WARNING) as captured,
        ):
            expired = self.client.post(
                reverse("account-activate"),
                {
                    "token": token,
                    "password1": password,
                    "password2": password,
                },
            )
            invalid = self.client.post(
                reverse("account-activate"),
                {
                    "token": f"invalid-{token}",
                    "password1": password,
                    "password2": password,
                },
            )
            self.client.post(
                reverse("landing"),
                {"username": raw_rfc, "password": password},
            )

        self.assertEqual(expired.status_code, 400)
        self.assertEqual(invalid.status_code, 400)
        logged = "\n".join(captured.output)
        self.assertNotIn(token, logged)
        self.assertNotIn(password, logged)
        self.assertNotIn(raw_rfc, logged)
        self.assertNotContains(expired, token, status_code=400)
        self.assertNotContains(invalid, token, status_code=400)

    def test_unverified_email_cannot_authenticate(self) -> None:
        user = User.objects.create_user(
            email="unverified.login@example.com",
            password="correct horse battery staple",
        )

        response = self.client.post(
            reverse("landing"),
            {
                "username": user.email,
                "password": "correct horse battery staple",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
