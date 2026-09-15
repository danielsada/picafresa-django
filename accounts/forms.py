from typing import Any, cast

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import User


class ActivationForm(forms.Form):
    token = forms.CharField(
        label="Código de activación",
        strip=True,
        widget=forms.PasswordInput(attrs={"autocomplete": "one-time-code"}),
    )
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirmar contraseña", widget=forms.PasswordInput)

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean() or {}
        password = cleaned_data.get("password1")
        if password and password != cleaned_data.get("password2"):
            self.add_error("password2", "Las contraseñas no coinciden.")
        if password:
            try:
                validate_password(password)
            except ValidationError as error:
                self.add_error("password1", error)
        return cleaned_data


class IdentifierAuthenticationForm(AuthenticationForm):
    username = forms.CharField(label="Correo electrónico o RFC", strip=True)


class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(label="Correo electrónico")

    def clean_email(self) -> str:
        email = cast(str, self.cleaned_data["email"])
        return email.strip().casefold()


class PasswordProofForm(forms.Form):
    token = forms.CharField(
        label="Código de recuperación",
        strip=True,
        widget=forms.PasswordInput(attrs={"autocomplete": "one-time-code"}),
    )
    password1 = forms.CharField(label="Nueva contraseña", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirmar contraseña", widget=forms.PasswordInput)

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean() or {}
        password = cleaned_data.get("password1")
        if password and password != cleaned_data.get("password2"):
            self.add_error("password2", "Las contraseñas no coinciden.")
        if password:
            try:
                validate_password(password)
            except ValidationError as error:
                self.add_error("password1", error)
        return cleaned_data


class EmailChangeForm(forms.Form):
    current_password = forms.CharField(label="Contraseña actual", widget=forms.PasswordInput)
    new_email = forms.EmailField(label="Nuevo correo electrónico")

    def __init__(self, user: User, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_current_password(self) -> str:
        password = cast(str, self.cleaned_data["current_password"])
        if not self.user.check_password(password):
            raise ValidationError("La contraseña actual no es correcta.")
        return password

    def clean_new_email(self) -> str:
        email = User.normalize_email(cast(str, self.cleaned_data["new_email"]))
        if User.objects.exclude(pk=self.user.pk).filter(email=email).exists():
            raise ValidationError("No se puede usar ese correo electrónico.")
        if email == self.user.email:
            raise ValidationError("Escribe un correo electrónico diferente.")
        return email


class EmailChangeProofForm(forms.Form):
    token = forms.CharField(
        label="Código de verificación",
        strip=True,
        widget=forms.PasswordInput(attrs={"autocomplete": "one-time-code"}),
    )
