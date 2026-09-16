from django.db.models import Q, QuerySet

from accounts.models import User

from .models import AssistanceProvider, Business, ProviderAssignment, Reseller, ScopedAssignment


def _active_assignments(user: User) -> QuerySet[ScopedAssignment]:
    return ScopedAssignment.objects.filter(
        user=user,
        revoked_at__isnull=True,
    )


def administered_resellers(user: User) -> QuerySet[Reseller]:
    if not user.is_active:
        return Reseller.objects.none()
    return Reseller.objects.filter(
        is_active=True,
        deleted_at__isnull=True,
        pk__in=_active_assignments(user)
        .filter(role=ScopedAssignment.Role.RESELLER_ADMIN)
        .values("reseller_id"),
    )


def administered_businesses(user: User) -> QuerySet[Business]:
    return Business.objects.filter(
        is_active=True,
        deleted_at__isnull=True,
        reseller__in=administered_resellers(user),
    ).select_related("reseller")


def administered_provider_assignments(user: User) -> QuerySet[ProviderAssignment]:
    return ProviderAssignment.objects.filter(
        business__in=administered_businesses(user),
        deleted_at__isnull=True,
        provider__is_active=True,
        provider__deleted_at__isnull=True,
    ).select_related("provider", "business__reseller")


def accessible_businesses(user: User) -> QuerySet[Business]:
    businesses = Business.objects.filter(
        is_active=True,
        deleted_at__isnull=True,
        reseller__is_active=True,
        reseller__deleted_at__isnull=True,
    )
    if not user.is_active:
        return businesses.none()
    if user.is_superuser:
        return businesses
    assignments = _active_assignments(user)
    return businesses.filter(
        Q(
            reseller__user_assignments__in=assignments.filter(
                role=ScopedAssignment.Role.RESELLER_ADMIN,
            ),
        )
        | Q(
            user_assignments__in=assignments.filter(
                role=ScopedAssignment.Role.TENANT_ADMIN,
            ),
        )
        | Q(
            provider_assignments__user_assignments__in=assignments.filter(
                role=ScopedAssignment.Role.PROVIDER_EMPLOYEE,
            ),
            provider_assignments__is_active=True,
            provider_assignments__deleted_at__isnull=True,
            provider_assignments__provider__is_active=True,
            provider_assignments__provider__deleted_at__isnull=True,
        )
    ).distinct()


def can_access_reseller(user: User, reseller: Reseller) -> bool:
    if not user.is_active or not reseller.is_active or reseller.deleted_at is not None:
        return False
    if user.is_superuser:
        return True
    return (
        _active_assignments(user)
        .filter(
            role=ScopedAssignment.Role.RESELLER_ADMIN,
            reseller=reseller,
        )
        .exists()
    )


def can_access_business(user: User, business: Business) -> bool:
    return accessible_businesses(user).filter(pk=business.pk).exists()


def can_access_provider(
    user: User,
    provider: AssistanceProvider,
    business: Business,
) -> bool:
    if (
        not user.is_active
        or not provider.is_active
        or provider.deleted_at is not None
        or not can_access_business(user, business)
    ):
        return False
    if user.is_superuser:
        return True
    assignments = _active_assignments(user)
    return assignments.filter(
        Q(
            role=ScopedAssignment.Role.PROVIDER_EMPLOYEE,
            provider_assignment__provider=provider,
            provider_assignment__business=business,
            provider_assignment__is_active=True,
            provider_assignment__deleted_at__isnull=True,
        )
        | Q(
            role=ScopedAssignment.Role.RESELLER_ADMIN,
            reseller=business.reseller,
            reseller__businesses__provider_assignments__provider=provider,
            reseller__businesses__provider_assignments__business=business,
            reseller__businesses__provider_assignments__is_active=True,
            reseller__businesses__provider_assignments__deleted_at__isnull=True,
        )
    ).exists()
