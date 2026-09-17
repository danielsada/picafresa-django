from django.db.models import QuerySet

from accounts.models import User

from .models import PlanEnrollment


def member_enrollments(user: User) -> QuerySet[PlanEnrollment]:
    if not user.is_active or user.email_verified_at is None:
        return PlanEnrollment.objects.none()
    return (
        PlanEnrollment.objects.select_related(
            "member",
            "business",
            "plan_version__plan__provider",
        )
        .prefetch_related("beneficiaries")
        .filter(member__account=user, member__deleted_at__isnull=True)
    )
