from typing import Any, cast

from django import forms
from django.forms import formset_factory

from accounts.models import User
from organizations.models import AssistanceProvider, Business, Reseller

from .models import PROVIDER_PERMANENCE, Plan
from .selectors import catalog_resellers
from .services import DraftTerms, ServiceTerms


class PlanForm(forms.Form):
    name = forms.CharField(label="Nombre del Plan", max_length=200)
    reseller = forms.ModelChoiceField(label="Revendedor", queryset=Reseller.objects.none())
    provider = forms.ModelChoiceField(
        label="Proveedor permanente",
        queryset=AssistanceProvider.objects.none(),
        help_text=PROVIDER_PERMANENCE,
    )
    internal_amount = forms.DecimalField(
        label="Importe interno", required=False, min_value=0, max_digits=12, decimal_places=2
    )
    currency = forms.RegexField(
        label="Moneda interna", regex=r"^[A-Z]{3}$", initial="MXN", max_length=3
    )

    def __init__(self, *args: Any, actor: User, plan: Plan | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["reseller"] = forms.ModelChoiceField(
            label="Revendedor", queryset=catalog_resellers(actor)
        )
        self.fields["provider"] = forms.ModelChoiceField(
            label="Proveedor permanente",
            queryset=AssistanceProvider.objects.filter(is_active=True, deleted_at__isnull=True),
            help_text=PROVIDER_PERMANENCE,
        )
        if plan is not None:
            del self.fields["reseller"]
            del self.fields["provider"]
            self.initial.update(name=plan.name)
            if actor.is_superuser:
                self.initial.update(internal_amount=plan.internal_amount, currency=plan.currency)
        if not actor.is_superuser:
            del self.fields["internal_amount"]
            del self.fields["currency"]


class DraftForm(forms.Form):
    effective_from = forms.DateField(
        label="Vigente desde", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )
    effective_until = forms.DateField(
        label="Vigente hasta (fecha exclusiva)",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    duration_months = forms.IntegerField(label="Duración en meses calendario", min_value=1)
    coverage_terms = forms.CharField(label="Condiciones de cobertura", widget=forms.Textarea)

    def terms(self, services: tuple[ServiceTerms, ...]) -> DraftTerms:
        return DraftTerms(
            effective_from=self.cleaned_data["effective_from"],
            effective_until=self.cleaned_data["effective_until"],
            duration_months=self.cleaned_data["duration_months"],
            coverage_terms=self.cleaned_data["coverage_terms"],
            services=services,
        )


class PlanAvailabilityForm(forms.Form):
    availability = forms.ChoiceField(label="Disponibilidad", choices=Plan.Availability)
    businesses = forms.ModelMultipleChoiceField(
        label="Empresas incluidas",
        queryset=Business.objects.none(),
        required=False,
        help_text="Se usa únicamente cuando eliges empresas seleccionadas.",
    )

    def __init__(self, *args: Any, plan: Plan, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        businesses = cast("forms.ModelMultipleChoiceField[Business]", self.fields["businesses"])
        businesses.queryset = Business.objects.filter(
            reseller_id=plan.reseller_id,
            is_active=True,
            deleted_at__isnull=True,
        )
        self.initial.update(
            availability=plan.availability,
            businesses=plan.selected_businesses.all(),
        )


class ServiceForm(forms.Form):
    name = forms.CharField(label="Servicio para el Afiliado", max_length=200)
    coverage_terms = forms.CharField(label="Condiciones del servicio", widget=forms.Textarea)


ServiceFormSet = formset_factory(
    ServiceForm,
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True,
    max_num=100,
    validate_max=True,
    absolute_max=100,
)
