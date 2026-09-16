from typing import cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from accounts.models import User
from audit.services import record_privileged_event

from .forms import DraftForm, PlanForm, ServiceFormSet
from .models import PROVIDER_PERMANENCE, Plan, PlanVersion
from .selectors import catalog_resellers, visible_plans
from .services import (
    ServiceTerms,
    create_draft,
    create_plan,
    publish_draft,
    update_draft,
    update_plan,
)


def _rejected_request(request: HttpRequest, target: Plan | PlanVersion) -> None:
    record_privileged_event(
        cast(User, request.user),
        "plan.rejected",
        target,
        {"operation": "request", "reason": "permission_denied"},
        scope_type="catalog",
    )


def _plan(request: HttpRequest, plan_id: int) -> Plan:
    plan = visible_plans(cast(User, request.user)).filter(pk=plan_id).first()
    if plan is None:
        if request.method == "POST":
            _rejected_request(request, Plan(pk=plan_id))
        raise Http404
    return plan


def _version(request: HttpRequest, version_id: int) -> PlanVersion:
    version = (
        PlanVersion.objects.select_related("plan__provider", "plan__reseller")
        .filter(pk=version_id, plan__in=visible_plans(cast(User, request.user)))
        .first()
    )
    if version is None:
        if request.method == "POST":
            _rejected_request(request, PlanVersion(pk=version_id))
        raise Http404
    return version


def _check_fields(request: HttpRequest, allowed: set[str], target: Plan | PlanVersion) -> None:
    protected = {
        "reseller",
        "reseller_id",
        "provider",
        "provider_id",
        "internal_amount",
        "currency",
        "author",
        "author_id",
        "published_by",
        "published_by_id",
        "status",
        "plan",
        "plan_id",
        "number",
        "published_at",
    }
    if request.method == "POST" and (protected - allowed).intersection(request.POST):
        _rejected_request(request, target)
        raise PermissionDenied


@login_required(login_url="landing")
@never_cache
@require_safe
def plan_list(request: HttpRequest) -> HttpResponse:
    actor = cast(User, request.user)
    if not actor.is_superuser and not catalog_resellers(actor).exists():
        raise PermissionDenied
    page = Paginator(visible_plans(actor), 20).get_page(request.GET.get("page"))
    return render(request, "catalog/plan_list.html", {"page": page})


@login_required(login_url="landing")
@never_cache
@require_safe
def plan_detail(request: HttpRequest, plan_id: int) -> HttpResponse:
    plan = _plan(request, plan_id)
    page = Paginator(plan.versions.all(), 20).get_page(request.GET.get("page"))
    return render(
        request,
        "catalog/plan_detail.html",
        {"plan": plan, "page": page, "provider_permanence": PROVIDER_PERMANENCE},
    )


@login_required(login_url="landing")
@never_cache
@require_http_methods(["GET", "POST"])
def plan_edit(request: HttpRequest, plan_id: int | None = None) -> HttpResponse:
    actor = cast(User, request.user)
    plan = _plan(request, plan_id) if plan_id is not None else None
    if plan is None and not catalog_resellers(actor).exists():
        if request.method == "POST":
            _rejected_request(request, Plan())
        raise PermissionDenied
    form = PlanForm(request.POST if request.method == "POST" else None, actor=actor, plan=plan)
    _check_fields(request, set(form.fields), plan or Plan())
    if request.method == "POST" and form.has_error("reseller", "invalid_choice"):
        _rejected_request(request, plan or Plan())
    if request.method == "POST" and form.is_valid():
        try:
            if plan is None:
                plan = create_plan(
                    actor=actor,
                    reseller_id=form.cleaned_data["reseller"].pk,
                    provider_id=form.cleaned_data["provider"].pk,
                    name=form.cleaned_data["name"],
                    internal_amount=form.cleaned_data.get("internal_amount"),
                    currency=form.cleaned_data.get("currency", "MXN"),
                )
            else:
                plan = update_plan(
                    actor=actor,
                    plan_id=plan.pk,
                    provider_id=plan.provider_id,
                    name=form.cleaned_data["name"],
                    internal_amount=form.cleaned_data.get("internal_amount"),
                    currency=form.cleaned_data.get("currency"),
                )
        except ValidationError as error:
            form.add_error(None, ValidationError(error.messages))
        else:
            messages.success(request, "Plan guardado.")
            return redirect("catalog:plan-detail", plan_id=plan.pk)
    return render(
        request,
        "catalog/plan_form.html",
        {"plan": plan, "form": form, "provider_permanence": PROVIDER_PERMANENCE},
    )


@login_required(login_url="landing")
@never_cache
@require_safe
def version_detail(request: HttpRequest, version_id: int) -> HttpResponse:
    version = _version(request, version_id)
    return render(request, "catalog/version_detail.html", {"version": version})


@login_required(login_url="landing")
@never_cache
@require_http_methods(["GET", "POST"])
def draft_edit(
    request: HttpRequest, plan_id: int | None = None, version_id: int | None = None
) -> HttpResponse:
    actor = cast(User, request.user)
    version = _version(request, version_id) if version_id is not None else None
    plan = version.plan if version is not None else _plan(request, cast(int, plan_id))
    _check_fields(request, set(), version or plan)
    if version is not None:
        if version.status != PlanVersion.Status.DRAFT:
            if request.method == "POST":
                _rejected_request(request, version)
            messages.error(request, "Las versiones publicadas y sus servicios son inmutables.")
            return render(request, "catalog/version_detail.html", {"version": version})
        if version.author_id != actor.pk:
            if request.method == "POST":
                _rejected_request(request, version)
            raise PermissionDenied
    initial = None
    initial_services = []
    if version is not None:
        initial = {
            "effective_from": version.effective_from,
            "effective_until": version.effective_until,
            "duration_months": version.duration_months,
            "coverage_terms": version.coverage_terms,
        }
        initial_services = list(version.services.values("name", "coverage_terms"))
    data = request.POST if request.method == "POST" else None
    form = DraftForm(data, initial=initial)
    services = ServiceFormSet(data, initial=initial_services, prefix="services")
    if request.method == "POST" and form.is_valid() and services.is_valid():
        if "add_service" in request.POST:
            if services.total_form_count() < 100:
                expanded = request.POST.copy()
                expanded["services-TOTAL_FORMS"] = str(services.total_form_count() + 1)
                services = ServiceFormSet(expanded, initial=initial_services, prefix="services")
            else:
                form.add_error(None, "Puedes incluir hasta 100 servicios por versión.")
        else:
            terms = form.terms(
                tuple(
                    ServiceTerms(name=row["name"], coverage_terms=row["coverage_terms"])
                    for row in services.cleaned_data
                    if row and not row.get("DELETE")
                )
            )
            try:
                if version is None:
                    saved = create_draft(actor=actor, plan_id=plan.pk, terms=terms)
                else:
                    saved = update_draft(actor=actor, version_id=version.pk, terms=terms)
            except ValidationError as error:
                form.add_error(None, ValidationError(error.messages))
            else:
                messages.success(request, "Borrador guardado.")
                return redirect("catalog:version-detail", version_id=saved.pk)
    return render(
        request,
        "catalog/draft_form.html",
        {"plan": plan, "version": version, "form": form, "services": services},
    )


@login_required(login_url="landing")
@never_cache
@require_POST
def version_publish(request: HttpRequest, version_id: int) -> HttpResponse:
    version = _version(request, version_id)
    _check_fields(request, set(), version)
    try:
        publish_draft(actor=cast(User, request.user), version_id=version_id)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "Versión publicada. Sus condiciones y servicios son inmutables.")
    return redirect("catalog:version-detail", version_id=version_id)
