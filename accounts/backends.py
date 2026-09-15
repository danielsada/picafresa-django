from typing import Any

from django.contrib.auth.backends import ModelBackend
from django.http import HttpRequest

from .models import GovernmentIdentifier, User
from .services import InvalidGovernmentIdentifier, government_identifier_digest


class IdentifierBackend(ModelBackend):
    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> User | None:
        del request
        identifier = username or kwargs.get(User.USERNAME_FIELD)
        if not isinstance(identifier, str) or password is None:
            return None
        user = self._user_for_identifier(identifier)
        if user is not None and user.check_password(password) and self.user_can_authenticate(user):
            return user
        User().set_password(password)
        return None

    def _user_for_identifier(self, identifier: str) -> User | None:
        try:
            if "@" in identifier:
                return User.objects.get(
                    email=User.normalize_email(identifier),
                    email_verified_at__isnull=False,
                )
            digest = government_identifier_digest(
                GovernmentIdentifier.Kind.MX_RFC,
                identifier,
            )
            return User.objects.get(
                government_identifiers__kind=GovernmentIdentifier.Kind.MX_RFC,
                government_identifiers__lookup_digest=digest,
                email_verified_at__isnull=False,
            )
        except (User.DoesNotExist, User.MultipleObjectsReturned, InvalidGovernmentIdentifier):
            return None
