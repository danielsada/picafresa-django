from typing import Any, cast

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse

from accounts.models import User
from audit.services import record_privileged_event

from .models import Plan, PlanVersion


class CatalogReadOnlyAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    actions = None
    change_list_template = "admin/catalog/change_list.html"

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: Plan | PlanVersion | None = None
    ) -> bool:
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: Plan | PlanVersion | None = None
    ) -> bool:
        return False

    def changeform_view(
        self,
        request: HttpRequest,
        object_id: str | None = None,
        form_url: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> HttpResponse:
        if request.method == "POST":
            record_privileged_event(
                cast(User, request.user),
                "plan.rejected",
                self.model(pk=object_id),
                {"operation": "admin_edit", "reason": "permission_denied"},
            )
            raise PermissionDenied("Usa el flujo de planes con revisión por otra persona.")
        return super().changeform_view(request, object_id, form_url, extra_context)


@admin.register(Plan)
class PlanAdmin(CatalogReadOnlyAdmin):
    list_display = (
        "name",
        "reseller",
        "provider",
        "availability",
        "internal_amount",
        "currency",
    )
    list_filter = ("reseller", "provider", "availability")
    search_fields = ("name",)
    list_select_related = ("reseller", "provider")


@admin.register(PlanVersion)
class PlanVersionAdmin(CatalogReadOnlyAdmin):
    list_display = ("plan", "number", "status", "author", "published_by", "published_at")
    list_filter = ("status", "plan__reseller")
    search_fields = ("plan__name",)
    list_select_related = ("plan", "author", "published_by")
