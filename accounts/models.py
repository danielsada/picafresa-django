from typing import ClassVar

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower

from .managers import UserManager


class User(AbstractUser):
    username = None  # type: ignore[assignment]
    email = models.EmailField("correo electrónico", unique=True)

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
