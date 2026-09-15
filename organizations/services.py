from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from audit.services import record_privileged_event

from .models import (
    AssistanceProvider,
    Business,
    ProviderAssignment,
    Reseller,
    ScopedAssignment,
)

LifecycleObject = Reseller | Business | AssistanceProvider | ProviderAssignment


def _require_platform_operator(actor: User) -> None:
    if not actor.is_active or not actor.is_superuser:
        raise PermissionDenied("Solo un operador de plataforma puede realizar este cambio.")


def assignment_scope(assignment: ScopedAssignment) -> tuple[str, str]:
    if assignment.reseller_id is not None:
        return "reseller", str(assignment.reseller_id)
    if assignment.business_id is not None:
        return "business", str(assignment.business_id)
    if assignment.provider_assignment_id is not None:
        return "provider_assignment", str(assignment.provider_assignment_id)
    raise ValueError("La asignación no tiene un alcance válido.")


def record_organization_change(
    organization: LifecycleObject,
    actor: User,
    changed_fields: list[str],
    *,
    created: bool,
) -> None:
    _require_platform_operator(actor)
    if created:
        action = "organization.created"
    elif "is_active" in changed_fields:
        action = (
            "organization.reactivated" if organization.is_active else "organization.deactivated"
        )
    else:
        action = "organization.updated"
    record_privileged_event(
        actor,
        action,
        organization,
        {
            "changed_fields": changed_fields,
            "is_active": organization.is_active,
        },
    )


@transaction.atomic
def soft_delete_organization(organization: LifecycleObject, actor: User) -> None:
    _require_platform_operator(actor)
    if organization.deleted_at is not None:
        raise ValueError("La organización ya está eliminada.")
    organization.is_active = False
    organization.deleted_at = timezone.now()
    organization.save(update_fields=["is_active", "deleted_at", "updated_at"])
    record_privileged_event(
        actor,
        "organization.soft_deleted",
        organization,
        {"is_active": False, "soft_deleted": True},
    )


def record_assignment_grant(
    assignment: ScopedAssignment,
    actor: User,
) -> None:
    _require_platform_operator(actor)
    scope_type, scope_reference = assignment_scope(assignment)
    record_privileged_event(
        actor,
        "assignment.granted",
        assignment,
        {
            "role": assignment.role,
            "scope_type": scope_type,
            "scope_reference": scope_reference,
        },
        scope_type=scope_type,
        scope_reference=scope_reference,
    )


@transaction.atomic
def revoke_assignment(assignment: ScopedAssignment, actor: User) -> None:
    _require_platform_operator(actor)
    if assignment.revoked_at is not None:
        raise ValueError("La asignación ya está revocada.")
    scope_type, scope_reference = assignment_scope(assignment)
    assignment.revoked_at = timezone.now()
    assignment.revoked_by = actor
    assignment.save(update_fields=["revoked_at", "revoked_by"])
    record_privileged_event(
        actor,
        "assignment.revoked",
        assignment,
        {
            "role": assignment.role,
            "scope_type": scope_type,
            "scope_reference": scope_reference,
            "revoked": True,
        },
        scope_type=scope_type,
        scope_reference=scope_reference,
    )
