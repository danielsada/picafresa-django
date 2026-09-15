from typing import Any

from django.db.models import Model

from accounts.models import User

from .context import current_correlation_id
from .models import AuditEvent


def record_user_security_event(
    user: User,
    action: str,
    changes: dict[str, Any],
) -> AuditEvent:
    return AuditEvent.objects.create(
        actor=user,
        action=action,
        object_type="user",
        object_reference=str(user.pk),
        active_scope_type="account",
        active_scope_reference=str(user.pk),
        correlation_id=current_correlation_id(),
        changes=changes,
    )


def record_privileged_event(
    actor: User,
    action: str,
    target: Model,
    changes: dict[str, Any],
    *,
    scope_type: str = "platform",
    scope_reference: str = "",
) -> AuditEvent:
    return AuditEvent.objects.create(
        actor=actor,
        action=action,
        object_type=target._meta.label_lower,
        object_reference=str(target.pk),
        active_scope_type=scope_type,
        active_scope_reference=scope_reference,
        correlation_id=current_correlation_id(),
        changes=changes,
    )
