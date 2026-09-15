from django.contrib import admin
from django.http import HttpRequest

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "occurred_at",
        "actor",
        "action",
        "object_type",
        "object_reference",
        "active_scope_type",
        "active_scope_reference",
        "correlation_id",
    )
    list_filter = ("action", "object_type", "active_scope_type")
    search_fields = ("action", "object_type", "object_reference", "actor__email")
    readonly_fields = (
        "actor",
        "action",
        "object_type",
        "object_reference",
        "active_scope_type",
        "active_scope_reference",
        "correlation_id",
        "changes",
        "occurred_at",
    )
    date_hierarchy = "occurred_at"

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: AuditEvent | None = None,
    ) -> bool:
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: AuditEvent | None = None,
    ) -> bool:
        return False
