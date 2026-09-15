from typing import Any

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from django.http import HttpRequest

from .models import AccountSession, User


@receiver(user_logged_in)
def record_account_session(
    sender: type[User],
    request: HttpRequest,
    user: User,
    **kwargs: Any,
) -> None:
    del sender, kwargs
    if request.session.session_key is None:
        request.session.save()
    session_key = request.session.session_key
    if session_key is not None:
        AccountSession.objects.update_or_create(
            session_key=session_key,
            defaults={"user": user},
        )


@receiver(user_logged_out)
def discard_account_session(
    sender: type[User],
    request: HttpRequest | None,
    user: User | None,
    **kwargs: Any,
) -> None:
    del sender, user, kwargs
    if request is not None and request.session.session_key is not None:
        AccountSession.objects.filter(session_key=request.session.session_key).delete()
