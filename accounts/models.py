from typing import Any, ClassVar

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from .managers import UserManager


class User(AbstractUser):
    username = None  # type: ignore[assignment]
    email = models.EmailField("correo electrónico", unique=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD: str = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    objects: ClassVar[UserManager] = UserManager()  # type: ignore[assignment]

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="uq_accounts_user_normalized_email",
            ),
        ]

    @classmethod
    def normalize_email(cls, email: str) -> str:
        return email.strip().casefold()

    def __str__(self) -> str:
        return self.email

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.email = self.normalize_email(self.email)
        super().save(*args, **kwargs)


class AccountProof(models.Model):
    class Purpose(models.TextChoices):
        ACTIVATION = "activation", "Activación"
        PASSWORD_RESET = "password_reset", "Restablecimiento de contraseña"
        EMAIL_CHANGE = "email_change", "Cambio de correo"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="account_proofs")
    purpose = models.CharField(max_length=20, choices=Purpose)
    token_digest = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    requested_email = models.EmailField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)


class GovernmentIdentifier(models.Model):
    class Kind(models.TextChoices):
        MX_RFC = "mx_rfc", "RFC de México"

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="government_identifiers",
    )
    kind = models.CharField(max_length=20, choices=Kind)
    lookup_digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("kind", "lookup_digest"),
                name="uq_government_identifier_kind_lookup",
            ),
        ]


class AccountSession(models.Model):
    session_key = models.CharField(max_length=40, primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="account_sessions")
    created_at = models.DateTimeField(default=timezone.now)
