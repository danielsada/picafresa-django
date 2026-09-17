from typing import cast

from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from enrollments.selectors import member_enrollments
from organizations.selectors import administered_resellers

from .forms import (
    ActivationForm,
    EmailChangeForm,
    EmailChangeProofForm,
    IdentifierAuthenticationForm,
    PasswordProofForm,
    PasswordResetRequestForm,
)
from .models import User
from .services import (
    InvalidAccountProof,
    activate_account,
    confirm_email_change,
    discard_user_session,
    invalidate_user_sessions,
    request_email_change,
    request_password_reset,
    reset_password,
)


class AccountLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True
    authentication_form = IdentifierAuthenticationForm

    def get_success_url(self) -> str:
        user = cast(User, self.request.user)
        if user.is_staff and user.is_superuser:
            return "/admin/"
        if administered_resellers(user).exists():
            return self.get_redirect_url() or reverse("organizations:portfolio")
        return super().get_success_url()


def activate(request: HttpRequest) -> HttpResponse:
    form = ActivationForm(request.POST or None)
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            user = activate_account(
                form.cleaned_data["token"],
                form.cleaned_data["password1"],
            )
        except InvalidAccountProof:
            form.add_error("token", "El código no es válido o ha vencido.")
            status = 400
        except ValidationError as error:
            form.add_error("password1", error)
        else:
            login(request, user, backend="accounts.backends.IdentifierBackend")
            return redirect("account-home")
    return render(request, "accounts/activate.html", {"form": form}, status=status)


@login_required
def home(request: HttpRequest) -> HttpResponse:
    user = cast(User, request.user)
    return render(
        request,
        "accounts/home.html",
        {
            "has_portfolio": administered_resellers(user).exists(),
            "member_enrollments": member_enrollments(user),
        },
    )


@require_POST
def logout_account(request: HttpRequest) -> HttpResponse:
    session_key = request.session.session_key
    logout(request)
    if session_key is not None:
        discard_user_session(session_key)
    return redirect("landing")


def password_reset(request: HttpRequest) -> HttpResponse:
    form = PasswordResetRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        request_password_reset(form.cleaned_data["email"])
        return redirect("password-reset-sent")
    return render(request, "accounts/password_reset.html", {"form": form})


def password_reset_sent(request: HttpRequest) -> HttpResponse:
    return render(request, "accounts/password_reset_sent.html")


def password_reset_confirm(request: HttpRequest) -> HttpResponse:
    form = PasswordProofForm(request.POST or None)
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            user = reset_password(
                form.cleaned_data["token"],
                form.cleaned_data["password1"],
            )
        except InvalidAccountProof:
            form.add_error("token", "El código no es válido o ha vencido.")
            status = 400
        except ValidationError as error:
            form.add_error("password1", error)
        else:
            invalidate_user_sessions(user)
            return redirect("landing")
    return render(
        request,
        "accounts/password_reset_confirm.html",
        {"form": form},
        status=status,
    )


@login_required
def email_change(request: HttpRequest) -> HttpResponse:
    user = cast(User, request.user)
    form = EmailChangeForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        request_email_change(user, form.cleaned_data["new_email"])
        return redirect("email-change-sent")
    return render(request, "accounts/email_change.html", {"form": form})


@login_required
def email_change_sent(request: HttpRequest) -> HttpResponse:
    return render(request, "accounts/email_change_sent.html")


@login_required
def email_change_confirm(request: HttpRequest) -> HttpResponse:
    user = cast(User, request.user)
    form = EmailChangeProofForm(request.POST or None)
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            confirm_email_change(user, form.cleaned_data["token"])
        except InvalidAccountProof:
            form.add_error("token", "El código no es válido o ha vencido.")
            status = 400
        else:
            invalidate_user_sessions(user)
            logout(request)
            return redirect("landing")
    return render(
        request,
        "accounts/email_change_confirm.html",
        {"form": form},
        status=status,
    )
