import calendar
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from accounts.models import User
from accounts.services import issue_activation
from audit.services import record_privileged_event
from catalog.models import Plan, PlanVersion
from catalog.services import resolve_available_plan_version
from organizations.models import ProviderAssignment
from organizations.selectors import administered_businesses

from .models import Beneficiary, Member, PlanEnrollment


@dataclass(frozen=True)
class EnrollmentTerms:
    member_id: int
    plan_id: int
    start_date: date
    explicit_end_date: date | None = None
    override_reason: str = ""
    allow_eligibility_override: bool = False
    preceding_enrollment_id: int | None = None


@dataclass(frozen=True)
class BeneficiaryDetails:
    full_name: str
    relationship: str
    date_of_birth: date | None
    country_code: str
    gender: str
    email: str = ""
    phone: str = ""
    attribution_source: str = ""
    do_not_contact: bool = False


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
            .filter(pk=member_id, business__in=businesses, deleted_at__isnull=True)
            .first()
        )
    if member is None:
        raise PermissionDenied
    return member


def _administered_enrollment(actor: User, enrollment_id: int) -> PlanEnrollment:
    enrollment = (
        PlanEnrollment.objects.select_related("member", "business").filter(pk=enrollment_id).first()
    )
    if enrollment is None:
        raise PermissionDenied
    _administered_member(actor, enrollment.member_id)
    return enrollment


@transaction.atomic
def add_beneficiary(
    *,
    actor: User,
    enrollment_id: int,
    details: BeneficiaryDetails,
) -> Beneficiary:
    enrollment = _administered_enrollment(actor, enrollment_id)
    beneficiary = Beneficiary(
        enrollment=enrollment,
        full_name=details.full_name.strip(),
        relationship=details.relationship.strip(),
        date_of_birth=details.date_of_birth,
        country_code=details.country_code.strip().upper(),
        gender=details.gender,
        email=details.email.strip().casefold(),
        phone=details.phone.strip(),
        attribution_source=details.attribution_source.strip(),
        do_not_contact=details.do_not_contact,
    )
    beneficiary.full_clean()
    beneficiary.save()
    record_privileged_event(
        actor,
        "enrollment.beneficiary_added",
        beneficiary,
        {"enrollment_id": enrollment.pk},
        scope_type="business",
        scope_reference=str(enrollment.business_id),
    )
    return beneficiary


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


class IdentityReviewRequired(ValidationError):
    pass


@transaction.atomic
def invite_member(*, actor: User, member_id: int) -> User:
    member = _administered_member(actor, member_id)
    normalized_email = User.normalize_email(member.email)
    if not normalized_email:
        raise ValidationError(
            "El Afiliado necesita un correo electrónico para recibir la invitación."
        )
    if member.deleted_at is not None or (
        Member.objects.filter(
            email=normalized_email,
            deleted_at__isnull=False,
        )
        .exclude(pk=member.pk)
        .exists()
    ):
        raise IdentityReviewRequired(
            "Existe una identidad eliminada que requiere revisión explícita."
        )
    if member.account_id is not None:
        raise ValidationError("El Afiliado ya tiene una cuenta vinculada.")
    account = User.objects.filter(email=normalized_email).first()
    account_created = account is None
    if account is not None and hasattr(account, "member"):
        raise ValidationError("El correo ya pertenece a otro Afiliado.")
    if account is not None and account.is_active != (account.email_verified_at is not None):
        raise IdentityReviewRequired(
            "La cuenta existente requiere revisión explícita antes de vincularla."
        )
    if account is None:
        account = User.objects.create_user(email=normalized_email, is_active=False)
    member.account = account
    member.save(update_fields=["account"])
    if not account.is_active:
        issue_activation(account)
    record_privileged_event(
        actor,
        "member.invited",
        member,
        {"account_created": account_created},
        scope_type="business",
        scope_reference=str(member.business_id),
    )
    return account


class RenewalGenerator(Protocol):
    def generate_due_renewals(self, *, as_of: date) -> tuple[PlanEnrollment, ...]: ...


class UnavailableRenewalGenerator:
    def generate_due_renewals(self, *, as_of: date) -> tuple[PlanEnrollment, ...]:
        del as_of
        raise RenewalGenerationUnavailable("La generación automática de renovaciones no existe.")
