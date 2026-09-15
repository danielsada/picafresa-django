from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import unicodedata
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .models import AccountProof, AccountSession, GovernmentIdentifier, User

PROOF_LIFETIME = timedelta(hours=24)


class InvalidAccountProof(ValueError):
    pass


class InvalidGovernmentIdentifier(ValueError):
    pass


def _proof_digest(purpose: str, token: str) -> str:
    message = f"{purpose}:{token}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def normalize_government_identifier(kind: str, value: str) -> str:
    if kind != GovernmentIdentifier.Kind.MX_RFC:
        raise InvalidGovernmentIdentifier("El tipo de identificador no es compatible.")
    normalized = re.sub(r"[\s-]+", "", unicodedata.normalize("NFKC", value)).upper()
    if re.fullmatch(r"[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}", normalized) is None:
        raise InvalidGovernmentIdentifier("El RFC no es válido.")
    return normalized


def government_identifier_digest(kind: str, value: str) -> str:
    normalized = normalize_government_identifier(kind, value)
    message = f"government-identifier:{kind}:{normalized}".encode()
    return hmac.new(
        settings.GOVERNMENT_IDENTIFIER_LOOKUP_KEY.encode(),
        message,
        hashlib.sha256,
    ).hexdigest()


def add_government_identifier(
    user: User,
    kind: str,
    value: str,
) -> GovernmentIdentifier:
    return GovernmentIdentifier.objects.create(
        user=user,
        kind=kind,
        lookup_digest=government_identifier_digest(kind, value),
    )


def issue_activation(user: User) -> None:
    if user.is_active or user.email_verified_at is not None:
        raise ValueError("La cuenta ya está activa.")
    token = secrets.token_urlsafe(32)
    AccountProof.objects.create(
        user=user,
        purpose=AccountProof.Purpose.ACTIVATION,
        token_digest=_proof_digest(AccountProof.Purpose.ACTIVATION, token),
        expires_at=timezone.now() + PROOF_LIFETIME,
    )
    send_mail(
        "Activa tu cuenta de Picafresa",
        f"Usa este código para activar tu cuenta.\n\nCódigo: {token}",
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
    )


def request_password_reset(email: str) -> None:
    try:
        user = User.objects.get(
            email=User.normalize_email(email),
            email_verified_at__isnull=False,
            is_active=True,
        )
    except User.DoesNotExist:
        return
    token = secrets.token_urlsafe(32)
    AccountProof.objects.create(
        user=user,
        purpose=AccountProof.Purpose.PASSWORD_RESET,
        token_digest=_proof_digest(AccountProof.Purpose.PASSWORD_RESET, token),
        expires_at=timezone.now() + PROOF_LIFETIME,
    )
    send_mail(
        "Restablece tu contraseña de Picafresa",
        f"Usa este código para restablecer tu contraseña.\n\nCódigo: {token}",
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
    )


@transaction.atomic
def reset_password(token: str, password: str) -> User:
    digest = _proof_digest(AccountProof.Purpose.PASSWORD_RESET, token)
    try:
        proof = AccountProof.objects.select_for_update().get(
            purpose=AccountProof.Purpose.PASSWORD_RESET,
            token_digest=digest,
            consumed_at__isnull=True,
        )
    except AccountProof.DoesNotExist as error:
        raise InvalidAccountProof("La prueba no es válida.") from error
    now = timezone.now()
    if proof.expires_at <= now:
        raise InvalidAccountProof("La prueba no es válida.")
    user = User.objects.select_for_update().get(pk=proof.user_id)
    validate_password(password, user)
    user.set_password(password)
    user.save(update_fields=["password"])
    proof.consumed_at = now
    proof.save(update_fields=["consumed_at"])
    AccountProof.objects.filter(
        user=user,
        purpose=AccountProof.Purpose.PASSWORD_RESET,
        consumed_at__isnull=True,
    ).update(consumed_at=now)
    return user


def request_email_change(user: User, new_email: str) -> None:
    normalized_email = User.normalize_email(new_email)
    if User.objects.exclude(pk=user.pk).filter(email=normalized_email).exists():
        raise ValueError("No se puede usar ese correo electrónico.")
    token = secrets.token_urlsafe(32)
    AccountProof.objects.create(
        user=user,
        purpose=AccountProof.Purpose.EMAIL_CHANGE,
        token_digest=_proof_digest(AccountProof.Purpose.EMAIL_CHANGE, token),
        expires_at=timezone.now() + PROOF_LIFETIME,
        requested_email=normalized_email,
    )
    send_mail(
        "Verifica tu nuevo correo de Picafresa",
        f"Usa este código para verificar tu nuevo correo.\n\nCódigo: {token}",
        settings.DEFAULT_FROM_EMAIL,
        [normalized_email],
    )


@transaction.atomic
def confirm_email_change(user: User, token: str) -> str:
    digest = _proof_digest(AccountProof.Purpose.EMAIL_CHANGE, token)
    try:
        proof = AccountProof.objects.select_for_update().get(
            user=user,
            purpose=AccountProof.Purpose.EMAIL_CHANGE,
            token_digest=digest,
            consumed_at__isnull=True,
        )
    except AccountProof.DoesNotExist as error:
        raise InvalidAccountProof("La prueba no es válida.") from error
    now = timezone.now()
    if proof.expires_at <= now or proof.requested_email is None:
        raise InvalidAccountProof("La prueba no es válida.")
    locked_user = User.objects.select_for_update().get(pk=user.pk)
    if User.objects.exclude(pk=locked_user.pk).filter(email=proof.requested_email).exists():
        raise InvalidAccountProof("La prueba no es válida.")
    old_email = locked_user.email
    locked_user.email = proof.requested_email
    locked_user.email_verified_at = now
    locked_user.save(update_fields=["email", "email_verified_at"])
    proof.consumed_at = now
    proof.save(update_fields=["consumed_at"])
    AccountProof.objects.filter(
        user=locked_user,
        purpose=AccountProof.Purpose.EMAIL_CHANGE,
        consumed_at__isnull=True,
    ).update(consumed_at=now)
    send_mail(
        "Tu correo de Picafresa cambió",
        "El correo de acceso a tu cuenta cambió. Si no fuiste tú, contacta a soporte.",
        settings.DEFAULT_FROM_EMAIL,
        [old_email],
    )
    return old_email


def invalidate_user_sessions(user: User) -> None:
    session_keys = list(
        AccountSession.objects.filter(user=user).values_list("session_key", flat=True)
    )
    Session.objects.filter(session_key__in=session_keys).delete()
    AccountSession.objects.filter(user=user).delete()


@transaction.atomic
def activate_account(token: str, password: str) -> User:
    digest = _proof_digest(AccountProof.Purpose.ACTIVATION, token)
    try:
        proof = (
            AccountProof.objects.select_for_update()
            .select_related("user")
            .get(
                purpose=AccountProof.Purpose.ACTIVATION,
                token_digest=digest,
                consumed_at__isnull=True,
            )
        )
    except AccountProof.DoesNotExist as error:
        raise InvalidAccountProof("La prueba no es válida.") from error

    now = timezone.now()
    user = User.objects.select_for_update().get(pk=proof.user_id)
    if proof.expires_at <= now or user.is_active or user.email_verified_at is not None:
        raise InvalidAccountProof("La prueba no es válida.")

    validate_password(password, user)
    user.set_password(password)
    user.is_active = True
    user.email_verified_at = now
    user.save(update_fields=["password", "is_active", "email_verified_at"])
    proof.consumed_at = now
    proof.save(update_fields=["consumed_at"])
    AccountProof.objects.filter(
        user=user,
        purpose=AccountProof.Purpose.ACTIVATION,
        consumed_at__isnull=True,
    ).update(consumed_at=now)
    return user
