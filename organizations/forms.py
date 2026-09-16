from django import forms

from .models import Business, ProviderAssignment


class PortfolioBusinessForm(forms.ModelForm):  # type: ignore[type-arg]
    class Meta:
        model = Business
        fields = ("name", "timezone")


class PortfolioProviderForm(forms.ModelForm):  # type: ignore[type-arg]
    class Meta:
        model = ProviderAssignment
        fields = (
            "contact_name_override",
            "contact_email_override",
            "contact_phone_override",
            "service_instructions_override",
        )
