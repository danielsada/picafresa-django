from typing import cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from accounts.models import User
from enrollments.models import PlanEnrollment

from .forms import PortfolioBusinessForm, PortfolioProviderForm, ProviderContractForm
from .selectors import (
    administered_businesses,
    administered_provider_assignments,
    administered_resellers,
)
from .services import (
    create_provider_contract,
    deactivate_provider_contract,
    update_portfolio_business,
    update_portfolio_provider,
)


@login_required(login_url="landing")
@never_cache
@require_safe
def portfolio(request: HttpRequest) -> HttpResponse:
    actor = cast(User, request.user)
    if not administered_resellers(actor).exists():
        raise PermissionDenied
    businesses = administered_businesses(actor).order_by("name", "pk")
    page = Paginator(businesses, 20).get_page(request.GET.get("page"))
    return render(request, "organizations/portfolio.html", {"page": page})


@login_required(login_url="landing")
@never_cache
@require_safe
def business_detail(request: HttpRequest, business_id: int) -> HttpResponse:
    actor = cast(User, request.user)
    business = get_object_or_404(administered_businesses(actor), pk=business_id)
    relationships = (
        administered_provider_assignments(actor)
        .filter(business=business)
        .order_by("provider__name", "pk")
    )
    page = Paginator(relationships, 20).get_page(request.GET.get("page"))
    enrollments = PlanEnrollment.objects.select_related("member", "plan_version__plan").filter(
        business=business
    )
    enrollment_page = Paginator(enrollments, 20).get_page(request.GET.get("polizas_page"))
    return render(
        request,
        "organizations/business_detail.html",
        {
            "business": business,
            "page": page,
            "enrollment_page": enrollment_page,
        },
    )


@login_required(login_url="landing")
@never_cache
@require_http_methods(["GET", "POST"])
def business_edit(request: HttpRequest, business_id: int) -> HttpResponse:
    actor = cast(User, request.user)
    business = get_object_or_404(administered_businesses(actor), pk=business_id)
    form = PortfolioBusinessForm(
        request.POST if request.method == "POST" else None, instance=business
    )
    if request.method == "POST" and form.is_valid():
        try:
            update_portfolio_business(
                actor=actor,
                business_id=business_id,
                name=form.cleaned_data["name"],
                timezone_name=form.cleaned_data["timezone"],
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Cambios guardados.")
            return redirect("organizations:business-detail", business_id=business_id)
    return render(request, "organizations/business_edit.html", {"business": business, "form": form})


@login_required(login_url="landing")
@never_cache
@require_http_methods(["GET", "POST"])
def provider_edit(request: HttpRequest, business_id: int, relationship_id: int) -> HttpResponse:
    actor = cast(User, request.user)
    relationship = get_object_or_404(
        administered_provider_assignments(actor), pk=relationship_id, business_id=business_id
    )
    form = PortfolioProviderForm(
        request.POST if request.method == "POST" else None, instance=relationship
    )
    if request.method == "POST" and form.is_valid():
        try:
            update_portfolio_provider(
                actor=actor,
                business_id=business_id,
                relationship_id=relationship_id,
                contact_name=form.cleaned_data["contact_name_override"],
                contact_email=form.cleaned_data["contact_email_override"],
                contact_phone=form.cleaned_data["contact_phone_override"],
                service_instructions=form.cleaned_data["service_instructions_override"],
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Cambios guardados.")
            return redirect("organizations:business-detail", business_id=business_id)
    return render(
        request,
        "organizations/provider_edit.html",
        {"relationship": relationship, "form": form},
    )


@login_required(login_url="landing")
@never_cache
@require_http_methods(["GET", "POST"])
def provider_contract_create(request: HttpRequest, business_id: int) -> HttpResponse:
    actor = cast(User, request.user)
    business = get_object_or_404(administered_businesses(actor), pk=business_id)
    form = ProviderContractForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            create_provider_contract(
                actor=actor,
                business_id=business.pk,
                provider_id=form.cleaned_data["provider"].pk,
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Contrato creado.")
            return redirect("organizations:business-detail", business_id=business.pk)
    return render(
        request,
        "organizations/provider_contract_form.html",
        {"business": business, "form": form},
    )


@login_required(login_url="landing")
@never_cache
@require_POST
def provider_contract_deactivate(
    request: HttpRequest,
    business_id: int,
    relationship_id: int,
) -> HttpResponse:
    actor = cast(User, request.user)
    try:
        deactivate_provider_contract(
            actor=actor,
            business_id=business_id,
            contract_id=relationship_id,
        )
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "Contrato inactivo.")
    return redirect("organizations:business-detail", business_id=business_id)
