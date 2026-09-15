from typing import Any

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
        correlation_id=current_correlation_id(),
        changes=changes,
    )
