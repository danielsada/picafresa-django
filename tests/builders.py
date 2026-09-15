from accounts.models import User
from organizations.models import (
    AssistanceProvider,
    Business,
    ProviderAssignment,
    Reseller,
    ScopedAssignment,
)


def create_business(*, name: str, reseller: Reseller) -> Business:
    return Business.objects.create(name=name, reseller=reseller)


def create_provider_assignment(
    *,
    business: Business,
    provider: AssistanceProvider,
) -> ProviderAssignment:
    return ProviderAssignment.objects.create(business=business, provider=provider)


def create_reseller_scope(
    *,
    user: User,
    reseller: Reseller,
    granted_by: User | None = None,
) -> ScopedAssignment:
    return ScopedAssignment.objects.create(
        user=user,
        role=ScopedAssignment.Role.RESELLER_ADMIN,
        reseller=reseller,
        granted_by=granted_by,
    )


def create_provider_scope(
    *,
    user: User,
    provider_assignment: ProviderAssignment,
    granted_by: User | None = None,
) -> ScopedAssignment:
    return ScopedAssignment.objects.create(
        user=user,
        role=ScopedAssignment.Role.PROVIDER_EMPLOYEE,
        provider_assignment=provider_assignment,
        granted_by=granted_by,
    )


def create_tenant_scope(
    *,
    user: User,
    business: Business,
    granted_by: User | None = None,
) -> ScopedAssignment:
    return ScopedAssignment.objects.create(
        user=user,
        role=ScopedAssignment.Role.TENANT_ADMIN,
        business=business,
        granted_by=granted_by,
    )
