from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from accounts.models import User
from audit.services import record_privileged_event
from organizations.models import AssistanceProvider

from .models import PROVIDER_PERMANENCE, Plan, PlanService, PlanVersion
from .selectors import catalog_resellers, visible_plans


@dataclass(frozen=True)
class ServiceTerms:
    name: str
    coverage_terms: str


@dataclass(frozen=True)
class DraftTerms:
    effective_from: date
    effective_until: date
    duration_months: int
    coverage_terms: str
    services: tuple[ServiceTerms, ...]


@contextmanager
def _catalog_change(actor: User, target: Plan | PlanVersion, operation: str) -> Iterator[None]:
    try:
        with transaction.atomic():
            yield
    except (PermissionDenied, ValidationError) as error:
        # Record after the failed mutation's savepoint has rolled back.
        record_privileged_event(
            actor,
            "plan.rejected",
            target,
            {
                "operation": operation,
                "reason": (
                    "permission_denied" if isinstance(error, PermissionDenied) else "invalid_change"
                ),
            },
            scope_type="catalog",
        )
        raise


def create_plan(
    *,
    actor: User,
    reseller_id: int,
    provider_id: int,
    name: str,
    internal_amount: Decimal | None = None,
    currency: str = "MXN",
) -> Plan:
    with _catalog_change(actor, Plan(), "create_plan"):
        reseller = catalog_resellers(actor).filter(pk=reseller_id).first()
        if reseller is None:
            raise PermissionDenied
        if not actor.is_superuser and (internal_amount is not None or currency != "MXN"):
            raise PermissionDenied
        provider = AssistanceProvider.objects.filter(
            pk=provider_id, is_active=True, deleted_at__isnull=True
        ).first()
        if provider is None:
            raise ValidationError("Selecciona un Proveedor activo.")
        plan = Plan(
            reseller=reseller,
            provider=provider,
            name=name,
            internal_amount=internal_amount,
            currency=currency,
        )
        plan.full_clean()
        plan.save()
        record_privileged_event(
            actor,
            "plan.created",
            plan,
            {},
            scope_type="reseller",
            scope_reference=str(reseller.pk),
        )
        return plan


def _editable_plan(actor: User, plan_id: int) -> Plan:
    plan = visible_plans(actor).select_for_update(of=("self",)).filter(pk=plan_id).first()
    if plan is None:
        raise PermissionDenied
    if not catalog_resellers(actor).filter(pk=plan.reseller_id).exists():
        raise PermissionDenied
    if not plan.provider.is_active or plan.provider.deleted_at is not None:
        raise ValidationError("El Proveedor del Plan no está activo.")
    return plan


def update_plan(
    *,
    actor: User,
    plan_id: int,
    name: str,
    provider_id: int,
    internal_amount: Decimal | None = None,
    currency: str | None = None,
) -> Plan:
    with _catalog_change(actor, Plan(pk=plan_id), "edit_plan"):
        plan = _editable_plan(actor, plan_id)
        if provider_id != plan.provider_id:
            raise ValidationError(PROVIDER_PERMANENCE)
        if not actor.is_superuser and (internal_amount is not None or currency is not None):
            raise PermissionDenied
        plan.name = name
        if actor.is_superuser:
            plan.internal_amount = internal_amount
            plan.currency = currency or "MXN"
        plan.full_clean()
        plan.save(update_fields=["name", "internal_amount", "currency"])
        record_privileged_event(
            actor,
            "plan.updated",
            plan,
            {},
            scope_type="reseller",
            scope_reference=str(plan.reseller_id),
        )
        return plan


def create_draft(*, actor: User, plan_id: int, terms: DraftTerms) -> PlanVersion:
    with _catalog_change(actor, Plan(pk=plan_id), "create_draft"):
        plan = _editable_plan(actor, plan_id)
        latest = plan.versions.aggregate(number=Max("number"))["number"] or 0
        version = PlanVersion(plan=plan, number=latest + 1, author=actor)
        _save_terms(version, terms)
        record_privileged_event(
            actor,
            "plan.drafted",
            version,
            {"number": version.number},
            scope_type="reseller",
            scope_reference=str(plan.reseller_id),
        )
        return version


def _save_terms(version: PlanVersion, terms: DraftTerms) -> None:
    if not terms.services:
        raise ValidationError("Agrega al menos un servicio para el Afiliado.")
    version.effective_from = terms.effective_from
    version.effective_until = terms.effective_until
    version.duration_months = terms.duration_months
    version.coverage_terms = terms.coverage_terms
    version.full_clean()
    version.save()
    for terms_service in terms.services:
        service = PlanService(
            version=version, name=terms_service.name, coverage_terms=terms_service.coverage_terms
        )
        service.full_clean()
        service.save()


def _locked_version(actor: User, version_id: int) -> PlanVersion:
    candidate = PlanVersion.objects.filter(pk=version_id, plan__in=visible_plans(actor)).first()
    if candidate is None:
        raise PermissionDenied
    plan = _editable_plan(actor, candidate.plan_id)
    version = PlanVersion.objects.select_for_update().get(pk=version_id, plan=plan)
    version.plan = plan
    return version


def update_draft(*, actor: User, version_id: int, terms: DraftTerms) -> PlanVersion:
    with _catalog_change(actor, PlanVersion(pk=version_id), "edit_draft"):
        version = _locked_version(actor, version_id)
        if version.status != PlanVersion.Status.DRAFT:
            raise ValidationError("Las versiones publicadas son inmutables.")
        if version.author_id != actor.pk:
            raise PermissionDenied("Solo el autor puede editar su borrador.")
        version.services.all().delete()
        _save_terms(version, terms)
        record_privileged_event(
            actor,
            "plan.draft_updated",
            version,
            {"number": version.number},
            scope_type="reseller",
            scope_reference=str(version.plan.reseller_id),
        )
        return version


def publish_draft(*, actor: User, version_id: int) -> PlanVersion:
    with _catalog_change(actor, PlanVersion(pk=version_id), "publish"):
        version = _locked_version(actor, version_id)
        if version.author_id == actor.pk:
            raise PermissionDenied("Otra persona autorizada debe publicar este borrador.")
        if version.status != PlanVersion.Status.DRAFT:
            raise ValidationError("Las versiones publicadas son inmutables.")
        if not version.services.exists():
            raise ValidationError("Agrega al menos un servicio para el Afiliado.")
        version.status = PlanVersion.Status.PUBLISHED
        version.published_by = actor
        version.published_at = timezone.now()
        version.full_clean()
        version.save(update_fields=["status", "published_by", "published_at"])
        record_privileged_event(
            actor,
            "plan.published",
            version,
            {"number": version.number},
            scope_type="reseller",
            scope_reference=str(version.plan.reseller_id),
        )
        return version
