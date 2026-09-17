from typing import cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from accounts.models import User
from organizations.selectors import administered_businesses

from .forms import BeneficiaryForm, EnrollmentCreateForm, EnrollmentTransitionForm
from .models import PlanEnrollment
from .services import (
    BeneficiaryDetails,
    EnrollmentTerms,
    add_beneficiary,
    create_enrollment,
    invite_member,
    renew_enrollment,
    transition_enrollment,
)


def _administered_enrollments(actor: User) -> QuerySet[PlanEnrollment]:
    return (
        PlanEnrollment.objects.select_related(
            "member",
            "business",
            "plan_version__plan__provider",
            "preceding_enrollment",
        )
        .prefetch_related("beneficiaries")
        .filter(business__in=administered_businesses(actor))
    )


@login_required(login_url="landing")
@never_cache
@require_http_methods(["GET", "POST"])
def enrollment_create(request: HttpRequest, business_id: int) -> HttpResponse:
    actor = cast(User, request.user)
    business = get_object_or_404(administered_businesses(actor), pk=business_id)
    form = EnrollmentCreateForm(
        request.POST if request.method == "POST" else None,
        business=business,
    )
    if request.method == "POST" and form.is_valid():
        try:
            enrollment = create_enrollment(
                actor=actor,
                terms=EnrollmentTerms(
                    member_id=form.cleaned_data["member"].pk,
                    plan_id=form.cleaned_data["plan"].pk,
                    start_date=form.cleaned_data["start_date"],
                    explicit_end_date=form.cleaned_data["explicit_end_date"],
                    override_reason=form.cleaned_data["override_reason"],
                    allow_eligibility_override=form.cleaned_data["allow_eligibility_override"],
                ),
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Póliza creada.")
            return redirect("enrollments:detail", enrollment_id=enrollment.pk)
    return render(
        request,
        "enrollments/enrollment_form.html",
        {"business": business, "form": form},
    )


@login_required(login_url="landing")
@never_cache
@require_safe
def enrollment_detail(request: HttpRequest, enrollment_id: int) -> HttpResponse:
    actor = cast(User, request.user)
    enrollment = get_object_or_404(_administered_enrollments(actor), pk=enrollment_id)
    transition_form = EnrollmentTransitionForm(enrollment=enrollment)
    return render(
        request,
        "enrollments/enrollment_detail.html",
        {"enrollment": enrollment, "transition_form": transition_form},
    )


@login_required(login_url="landing")
@never_cache
@require_http_methods(["GET", "POST"])
def beneficiary_create(request: HttpRequest, enrollment_id: int) -> HttpResponse:
    actor = cast(User, request.user)
    enrollment = get_object_or_404(_administered_enrollments(actor), pk=enrollment_id)
    form = BeneficiaryForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        add_beneficiary(
            actor=actor,
            enrollment_id=enrollment.pk,
            details=BeneficiaryDetails(
                full_name=form.cleaned_data["full_name"],
                relationship=form.cleaned_data["relationship"],
                date_of_birth=form.cleaned_data["date_of_birth"],
                country_code=form.cleaned_data["country_code"],
                gender=form.cleaned_data["gender"],
                email=form.cleaned_data["email"],
                phone=form.cleaned_data["phone"],
                attribution_source=form.cleaned_data["attribution_source"],
                do_not_contact=form.cleaned_data["do_not_contact"],
            ),
        )
        messages.success(request, "Beneficiario agregado.")
        return redirect("enrollments:detail", enrollment_id=enrollment.pk)
    return render(
        request,
        "enrollments/beneficiary_form.html",
        {"enrollment": enrollment, "form": form},
    )


@login_required(login_url="landing")
@never_cache
@require_POST
def member_invite(request: HttpRequest, enrollment_id: int) -> HttpResponse:
    actor = cast(User, request.user)
    enrollment = get_object_or_404(_administered_enrollments(actor), pk=enrollment_id)
    try:
        invite_member(actor=actor, member_id=enrollment.member_id)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "Invitación enviada.")
    return redirect("enrollments:detail", enrollment_id=enrollment.pk)


@login_required(login_url="landing")
@never_cache
@require_POST
def enrollment_transition(request: HttpRequest, enrollment_id: int) -> HttpResponse:
    actor = cast(User, request.user)
    enrollment = get_object_or_404(_administered_enrollments(actor), pk=enrollment_id)
    form = EnrollmentTransitionForm(request.POST, enrollment=enrollment)
    if form.is_valid():
        try:
            transition_enrollment(
                actor=actor,
                enrollment_id=enrollment.pk,
                target_status=form.cleaned_data["status"],
            )
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Estado de la Póliza actualizado.")
    else:
        messages.error(request, "Selecciona una transición permitida.")
    return redirect("enrollments:detail", enrollment_id=enrollment.pk)


@login_required(login_url="landing")
@never_cache
@require_POST
def enrollment_renew(request: HttpRequest, enrollment_id: int) -> HttpResponse:
    actor = cast(User, request.user)
    enrollment = get_object_or_404(_administered_enrollments(actor), pk=enrollment_id)
    try:
        renewal = renew_enrollment(actor=actor, enrollment_id=enrollment.pk)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
        return redirect("enrollments:detail", enrollment_id=enrollment.pk)
    messages.success(request, "Póliza renovada.")
    return redirect("enrollments:detail", enrollment_id=renewal.pk)


# Create your views here.
