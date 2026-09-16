import calendar
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from accounts.models import User
from audit.services import record_privileged_event
from catalog.models import Plan, PlanVersion
from catalog.services import resolve_available_plan_version
from organizations.models import ProviderAssignment
from organizations.selectors import administered_businesses

from .models import Member, PlanEnrollment


@dataclass(frozen=True)
class EnrollmentTerms:
    member_id: int
    plan_id: int
    start_date: date
    explicit_end_date: date | None = None
    override_reason: str = ""
    allow_eligibility_override: bool = False
    preceding_enrollment_id: int | None = None


ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    PlanEnrollment.Status.PENDING_PAYMENT: frozenset(
        (PlanEnrollment.Status.ACTIVE, PlanEnrollment.Status.CANCELLED)
    ),
    PlanEnrollment.Status.ACTIVE: frozenset(
        (
            PlanEnrollment.Status.SUSPENDED,
            PlanEnrollment.Status.EXPIRED,
            PlanEnrollment.Status.CANCELLED,
        )
    ),
    PlanEnrollment.Status.SUSPENDED: frozenset(
        (
            PlanEnrollment.Status.ACTIVE,
            PlanEnrollment.Status.EXPIRED,
            PlanEnrollment.Status.CANCELLED,
        )
    ),
    PlanEnrollment.Status.EXPIRED: frozenset(),
    PlanEnrollment.Status.CANCELLED: frozenset(),
}


def add_calendar_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def is_renewal_eligible(*, plan: Plan, member: Member) -> bool:
    return plan.auto_renew_enabled and member.auto_renew_allowed


def _administered_member(actor: User, member_id: int) -> Member:
    businesses = administered_businesses(actor)
    if actor.is_active and actor.is_superuser:
        member = Member.objects.select_related("business__reseller").filter(pk=member_id).first()
    else:
        member = (
            Member.objects.select_related("business__reseller")
            .filter(pk=member_id, business__in=businesses)
            .first()
        )
    if member is None:
        raise PermissionDenied
    return member


def _version_for_terms(actor: User, member: Member, terms: EnrollmentTerms) -> PlanVersion:
    version = resolve_available_plan_version(
        business_id=member.business_id,
        plan_id=terms.plan_id,
        on_date=terms.start_date,
    )
    if version is not None:
        return version
    if not terms.allow_eligibility_override:
        raise ValidationError("El Plan no está disponible y vigente para este Afiliado.")
    if not terms.override_reason.strip():
        raise ValidationError("Explica el motivo de la excepción de elegibilidad.")
    version = (
        PlanVersion.objects.select_related("plan__reseller", "plan__provider")
        .filter(
            plan_id=terms.plan_id,
            plan__reseller_id=member.business.reseller_id,
            status=PlanVersion.Status.PUBLISHED,
            effective_from__lte=terms.start_date,
            effective_until__gt=terms.start_date,
        )
        .order_by("-number")
        .first()
    )
    if version is None:
        raise ValidationError("No existe una versión publicada y vigente para la excepción.")
    return version


@transaction.atomic
def create_enrollment(*, actor: User, terms: EnrollmentTerms) -> PlanEnrollment:
    member = _administered_member(actor, terms.member_id)
    version = _version_for_terms(actor, member, terms)
    calculated_end = add_calendar_months(terms.start_date, version.duration_months)
    end_date = terms.explicit_end_date or calculated_end
    has_end_override = end_date != calculated_end
    if (has_end_override or terms.allow_eligibility_override) and not terms.override_reason.strip():
        raise ValidationError("Explica el motivo de la excepción.")
    if end_date <= terms.start_date:
        raise ValidationError("El fin exclusivo debe ser posterior al inicio.")
    assignment = (
        ProviderAssignment.objects.select_related("provider")
        .filter(
            business=member.business,
            provider=version.plan.provider,
            is_active=True,
            deleted_at__isnull=True,
        )
        .first()
    )
    provider = version.plan.provider
    enrollment = PlanEnrollment(
        member=member,
        business=member.business,
        plan_version=version,
        preceding_enrollment_id=terms.preceding_enrollment_id,
        start_date=terms.start_date,
        end_date=end_date,
        duration_months=version.duration_months,
        provider_contact_name=(
            assignment.effective_contact_name if assignment else provider.contact_name
        ),
        provider_contact_email=(
            assignment.effective_contact_email if assignment else provider.contact_email
        ),
        provider_contact_phone=(
            assignment.effective_contact_phone if assignment else provider.contact_phone
        ),
        provider_service_instructions=(
            assignment.effective_service_instructions
            if assignment
            else provider.service_instructions
        ),
        override_reason=terms.override_reason.strip(),
        created_by=actor,
    )
    enrollment.full_clean()
    enrollment.save()
    record_privileged_event(
        actor,
        "enrollment.created",
        enrollment,
        {
            "status": enrollment.status,
            "eligibility_override": terms.allow_eligibility_override,
            "end_override": has_end_override,
        },
        scope_type="business",
        scope_reference=str(member.business_id),
    )
    if has_end_override or terms.allow_eligibility_override:
        record_privileged_event(
            actor,
            "enrollment.eligibility_overridden",
            enrollment,
            {
                "eligibility_override": terms.allow_eligibility_override,
                "end_override": has_end_override,
                "reason": enrollment.override_reason,
            },
            scope_type="business",
            scope_reference=str(member.business_id),
        )
    return enrollment


@transaction.atomic
def transition_enrollment(
    *,
    actor: User,
    enrollment_id: int,
    target_status: PlanEnrollment.Status,
) -> PlanEnrollment:
    enrollment = (
        PlanEnrollment.objects.select_for_update()
        .select_related("member")
        .filter(pk=enrollment_id)
        .first()
    )
    if enrollment is None:
        raise PermissionDenied
    _administered_member(actor, enrollment.member_id)
    if target_status not in ALLOWED_TRANSITIONS[enrollment.status]:
        raise ValidationError("La transición de estado no está permitida.")
    previous_status = enrollment.status
    enrollment.status = target_status
    enrollment.full_clean()
    enrollment.save(update_fields=["status"])
    record_privileged_event(
        actor,
        "enrollment.transitioned",
        enrollment,
        {"from": previous_status, "to": target_status},
        scope_type="business",
        scope_reference=str(enrollment.business_id),
    )
    return enrollment


@transaction.atomic
def renew_enrollment(*, actor: User, enrollment_id: int) -> PlanEnrollment:
    preceding = (
        PlanEnrollment.objects.select_for_update()
        .select_related("member", "plan_version__plan")
        .filter(pk=enrollment_id)
        .first()
    )
    if preceding is None:
        raise PermissionDenied
    _administered_member(actor, preceding.member_id)
    if hasattr(preceding, "renewal"):
        raise ValidationError("La Póliza ya tiene una renovación.")
    plan = preceding.plan_version.plan
    if not is_renewal_eligible(plan=plan, member=preceding.member):
        raise ValidationError("La renovación automática no está permitida.")
    renewal = create_enrollment(
        actor=actor,
        terms=EnrollmentTerms(
            member_id=preceding.member_id,
            plan_id=plan.pk,
            start_date=preceding.end_date,
            preceding_enrollment_id=preceding.pk,
        ),
    )
    record_privileged_event(
        actor,
        "enrollment.renewed",
        renewal,
        {"preceding_enrollment_id": preceding.pk},
        scope_type="business",
        scope_reference=str(renewal.business_id),
    )
    return renewal


class RenewalGenerationUnavailable(RuntimeError):
    pass


class RenewalGenerator(Protocol):
    def generate_due_renewals(self, *, as_of: date) -> tuple[PlanEnrollment, ...]: ...


class UnavailableRenewalGenerator:
    def generate_due_renewals(self, *, as_of: date) -> tuple[PlanEnrollment, ...]:
        del as_of
        raise RenewalGenerationUnavailable("La generación automática de renovaciones no existe.")
