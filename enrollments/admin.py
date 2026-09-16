from typing import Any

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse

from .models import Member, PlanEnrollment


class EnrollmentReadOnlyAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    actions = None

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: Member | PlanEnrollment | None = None,
    ) -> bool:
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: Member | PlanEnrollment | None = None,
    ) -> bool:
        return False

    def get_readonly_fields(
        self,
        request: HttpRequest,
        obj: Member | PlanEnrollment | None = None,
    ) -> tuple[str, ...]:
        del request, obj
        return tuple(field.name for field in self.model._meta.fields)

    def changeform_view(
        self,
        request: HttpRequest,
        object_id: str | None = None,
        form_url: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> HttpResponse:
        if request.method == "POST":
            raise PermissionDenied
        return super().changeform_view(request, object_id, form_url, extra_context)


@admin.register(Member)
class MemberAdmin(EnrollmentReadOnlyAdmin):
    list_display = ("full_name", "business", "auto_renew_allowed", "created_at")
    list_filter = ("business__reseller", "business", "auto_renew_allowed")
    search_fields = ("full_name",)
    list_select_related = ("business",)


@admin.register(PlanEnrollment)
class PlanEnrollmentAdmin(EnrollmentReadOnlyAdmin):
    list_display = (
        "member",
        "business",
        "plan_name",
        "status",
        "start_date",
        "end_date",
    )
    list_filter = ("status", "business__reseller", "business")
    search_fields = ("member__full_name", "plan_version__plan__name")
    list_select_related = ("member", "business", "plan_version__plan")

    @admin.display(description="Plan", ordering="plan_version__plan__name")
    def plan_name(self, enrollment: PlanEnrollment) -> str:
        return enrollment.plan_name
