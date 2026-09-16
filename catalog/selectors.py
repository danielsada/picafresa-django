from django.db.models import QuerySet

from accounts.models import User
from organizations.models import Reseller
from organizations.selectors import administered_resellers

from .models import Plan


def catalog_resellers(actor: User) -> QuerySet[Reseller]:
    if actor.is_active and actor.is_superuser:
        return Reseller.objects.filter(is_active=True, deleted_at__isnull=True)
    return administered_resellers(actor)


def visible_plans(actor: User) -> QuerySet[Plan]:
    plans = Plan.objects.select_related("reseller", "provider")
    if actor.is_active and actor.is_superuser:
        return plans
    return plans.filter(reseller__in=catalog_resellers(actor))
