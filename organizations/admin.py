from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from django.contrib import admin
from django.db.models import QuerySet
from django.forms import ModelForm
from django.http import HttpRequest

from accounts.models import User

from .models import AssistanceProvider, Business, ProviderAssignment, Reseller, ScopedAssignment
from .services import (
    LifecycleObject,
    record_assignment_change,
    record_organization_change,
    revoke_assignment,
    soft_delete_organization,
)


class OrganizationLifecycleAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    readonly_fields = ("deleted_at", "created_at", "updated_at")

    def save_model(
        self,
        request: HttpRequest,
        obj: LifecycleObject,
        form: ModelForm[Any],
        change: bool,
    ) -> None:
        super().save_model(request, obj, form, change)
        record_organization_change(
            obj,
            cast(User, request.user),
            list(form.changed_data),
            created=not change,
        )

    def delete_model(self, request: HttpRequest, obj: LifecycleObject) -> None:
        soft_delete_organization(obj, cast(User, request.user))

    def delete_queryset(
        self,
        request: HttpRequest,
        queryset: QuerySet[LifecycleObject],
    ) -> None:
        for organization in queryset:
            soft_delete_organization(organization, cast(User, request.user))

    def get_deleted_objects(
        self,
        objs: Sequence[Any] | QuerySet[Any, Any],
        request: HttpRequest,
    ) -> tuple[list[str], dict[str, int], set[str], list[str]]:
        return (
            [str(obj) for obj in objs],
            {str(self.model._meta.verbose_name_plural): len(objs)},
            set(),
            [],
        )

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: LifecycleObject | None = None,
    ) -> bool:
        return obj is None or obj.deleted_at is None

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: LifecycleObject | None = None,
    ) -> bool:
        return obj is None or obj.deleted_at is None


@admin.register(Reseller)
class ResellerAdmin(OrganizationLifecycleAdmin):
    list_display = ("name", "is_active", "deleted_at")
    search_fields = ("name",)


@admin.register(Business)
class BusinessAdmin(OrganizationLifecycleAdmin):
    list_display = ("name", "reseller", "timezone", "is_active", "deleted_at")
    list_filter = ("reseller", "is_active")
    search_fields = ("name", "reseller__name")


@admin.register(AssistanceProvider)
class AssistanceProviderAdmin(OrganizationLifecycleAdmin):
    list_display = ("name", "contact_name", "contact_email", "contact_phone", "is_active")
    search_fields = ("name", "contact_name", "contact_email", "contact_phone")


@admin.register(ProviderAssignment)
class ProviderAssignmentAdmin(OrganizationLifecycleAdmin):
    list_display = (
        "business",
        "provider",
        "effective_contact_name",
        "effective_contact_email",
        "effective_contact_phone",
        "is_active",
    )
    list_filter = ("business__reseller", "provider", "is_active")
    search_fields = ("business__name", "provider__name")


@admin.register(ScopedAssignment)
class ScopedAssignmentAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("user", "role", "scope", "granted_by", "created_at", "revoked_at")
    list_filter = ("role", "revoked_at")
    search_fields = (
        "user__email",
        "reseller__name",
        "business__name",
        "provider_assignment__provider__name",
    )
    readonly_fields = ("granted_by", "revoked_at", "revoked_by", "created_at")

    @admin.display(description="alcance")
    def scope(self, assignment: ScopedAssignment) -> object:
        return assignment.reseller or assignment.business or assignment.provider_assignment

    def save_model(
        self,
        request: HttpRequest,
        obj: ScopedAssignment,
        form: ModelForm[Any],
        change: bool,
    ) -> None:
        actor = cast(User, request.user)
        if not change:
            obj.granted_by = actor
        super().save_model(request, obj, form, change)
        record_assignment_change(
            obj,
            actor,
            list(form.changed_data),
            created=not change,
        )

    def delete_model(self, request: HttpRequest, obj: ScopedAssignment) -> None:
        revoke_assignment(obj, cast(User, request.user))

    def delete_queryset(
        self,
        request: HttpRequest,
        queryset: QuerySet[ScopedAssignment],
    ) -> None:
        for assignment in queryset:
            revoke_assignment(assignment, cast(User, request.user))

    def get_deleted_objects(
        self,
        objs: Sequence[Any] | QuerySet[Any, Any],
        request: HttpRequest,
    ) -> tuple[list[str], dict[str, int], set[str], list[str]]:
        return (
            [str(obj) for obj in objs],
            {str(self.model._meta.verbose_name_plural): len(objs)},
            set(),
            [],
        )

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: ScopedAssignment | None = None,
    ) -> bool:
        return obj is None or obj.revoked_at is None

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: ScopedAssignment | None = None,
    ) -> bool:
        return obj is None or obj.revoked_at is None
