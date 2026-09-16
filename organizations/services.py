from django.core.exceptions import PermissionDenied, ValidationError
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
from .selectors import administered_businesses, administered_provider_assignments

LifecycleObject = Reseller | Business | AssistanceProvider | ProviderAssignment


@transaction.atomic
def update_portfolio_business(
    *,
    actor: User,
    business_id: int,
    name: str,
    timezone_name: str,
) -> Business:
    business = (
        administered_businesses(actor)
        .select_for_update(of=("self",))
        .filter(pk=business_id)
        .first()
    )
    if business is None:
        raise PermissionDenied
    changed_fields = [
        field
        for field, value in (("name", name), ("timezone", timezone_name))
        if getattr(business, field) != value
    ]
    business.name = name
    business.timezone = timezone_name
    business.full_clean()
    if changed_fields:
        business.save(update_fields=[*changed_fields, "updated_at"])
        record_privileged_event(
            actor,
            "organization.updated",
            business,
            {"changed_fields": changed_fields},
            scope_type="reseller",
            scope_reference=str(business.reseller_id),
        )
    return business


@transaction.atomic
def update_portfolio_provider(
    *,
    actor: User,
    business_id: int,
    relationship_id: int,
    contact_name: str,
    contact_email: str,
    contact_phone: str,
    service_instructions: str,
) -> ProviderAssignment:
    relationship = (
        administered_provider_assignments(actor)
        .select_for_update(of=("self",))
        .filter(pk=relationship_id, business_id=business_id)
        .first()
    )
    if relationship is None:
        raise PermissionDenied
    values = {
        "contact_name_override": contact_name,
        "contact_email_override": contact_email,
        "contact_phone_override": contact_phone,
        "service_instructions_override": service_instructions,
    }
    changed_fields = [
        field for field, value in values.items() if getattr(relationship, field) != value
    ]
    for field, value in values.items():
        setattr(relationship, field, value)
    relationship.full_clean()
    if changed_fields:
        relationship.save(update_fields=[*changed_fields, "updated_at"])
        record_privileged_event(
            actor,
            "organization.updated",
            relationship,
            {"changed_fields": changed_fields},
            scope_type="reseller",
            scope_reference=str(relationship.business.reseller_id),
        )
    return relationship


@transaction.atomic
def create_provider_contract(
    *,
    actor: User,
    business_id: int,
    provider_id: int,
) -> ProviderAssignment:
    business = (
        administered_businesses(actor)
        .select_for_update(of=("self",))
        .filter(pk=business_id)
        .first()
    )
    if business is None:
        raise PermissionDenied
    provider = AssistanceProvider.objects.filter(
        pk=provider_id,
        is_active=True,
        deleted_at__isnull=True,
    ).first()
    if provider is None:
        raise ValidationError("Selecciona un Proveedor activo.")
    contract = ProviderAssignment(business=business, provider=provider)
    contract.full_clean()
    contract.save()
    record_privileged_event(
        actor,
        "provider_contract.created",
        contract,
        {},
        scope_type="reseller",
        scope_reference=str(business.reseller_id),
    )
    return contract


@transaction.atomic
def deactivate_provider_contract(
    *,
    actor: User,
    business_id: int,
    contract_id: int,
) -> ProviderAssignment:
    contract = (
        administered_provider_assignments(actor)
        .select_for_update(of=("self",))
        .filter(pk=contract_id, business_id=business_id)
        .first()
    )
    if contract is None:
        raise PermissionDenied
    if not contract.is_active:
        raise ValidationError("El contrato ya está inactivo.")
    contract.is_active = False
    contract.save(update_fields=["is_active", "updated_at"])
    record_privileged_event(
        actor,
        "provider_contract.deactivated",
        contract,
        {},
        scope_type="reseller",
        scope_reference=str(contract.business.reseller_id),
    )
    return contract


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
    raise ValueError("La asignación no indica para quién se otorgan los permisos.")


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
