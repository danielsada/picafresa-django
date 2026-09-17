from typing import Any, cast

from django import forms

from catalog.models import Plan
from organizations.models import Business

from .models import Beneficiary, Member, PlanEnrollment
from .services import ALLOWED_TRANSITIONS


class EnrollmentCreateForm(forms.Form):
    member = forms.ModelChoiceField(label="Afiliado", queryset=Member.objects.none())
    plan = forms.ModelChoiceField(label="Plan", queryset=Plan.objects.none())
    start_date = forms.DateField(
        label="Fecha de inicio", widget=forms.DateInput(attrs={"type": "date"})
    )
    explicit_end_date = forms.DateField(
        label="Fin exclusivo excepcional",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    allow_eligibility_override = forms.BooleanField(
        label="Autorizar excepción de elegibilidad",
        required=False,
    )
    override_reason = forms.CharField(
        label="Motivo de la excepción",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args: Any, business: Business, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        member = cast("forms.ModelChoiceField[Member]", self.fields["member"])
        plan = cast("forms.ModelChoiceField[Plan]", self.fields["plan"])
        member.queryset = Member.objects.filter(business=business)
        plan.queryset = Plan.objects.filter(reseller=business.reseller)


class EnrollmentTransitionForm(forms.Form):
    status = forms.ChoiceField(label="Nuevo estado")

    def __init__(self, *args: Any, enrollment: PlanEnrollment, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        labels = dict(PlanEnrollment.Status.choices)
        status_field = cast(forms.ChoiceField, self.fields["status"])
        status_field.choices = [
            (status, labels[status]) for status in ALLOWED_TRANSITIONS[enrollment.status]
        ]


class BeneficiaryForm(forms.ModelForm):  # type: ignore[type-arg]
    class Meta:
        model = Beneficiary
        fields = (
            "full_name",
            "relationship",
            "date_of_birth",
            "country_code",
            "gender",
            "email",
            "phone",
            "attribution_source",
            "do_not_contact",
        )
        widgets = {"date_of_birth": forms.DateInput(attrs={"type": "date"})}
