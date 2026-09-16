import re
from pathlib import PurePosixPath

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Q
from django.urls import reverse

from organizations.models import AssistanceProvider, Business, Reseller

PROVIDER_PERMANENCE = (
    "El Proveedor es permanente. Para cambiarlo debes crear un nuevo Plan; "
    "las versiones anteriores conservan su Proveedor."
)


def validate_service_channels(value: object) -> None:
    allowed = {choice.value for choice in PlanService.ServiceChannel}
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(channel, str) or channel not in allowed for channel in value)
        or len(value) != len(set(value))
    ):
        raise ValidationError("Selecciona uno o más canales de servicio válidos.")


def validate_coverage_image_reference(value: str) -> None:
    path = PurePosixPath(value)
    valid = re.fullmatch(
        r"catalog/coverage-images/[A-Za-z0-9][A-Za-z0-9._/-]*\.(?:jpe?g|png|webp)",
        value,
        flags=re.IGNORECASE,
    )
    if path.is_absolute() or ".." in path.parts or valid is None:
        raise ValidationError(
            "Usa una referencia de imagen válida del almacenamiento de coberturas."
        )


class Plan(models.Model):
    class Availability(models.TextChoices):
        ALL_BUSINESSES = "all_businesses", "Todas las empresas"
        SELECTED_BUSINESSES = "selected_businesses", "Empresas seleccionadas"

    reseller = models.ForeignKey(
        Reseller, on_delete=models.PROTECT, related_name="plans", verbose_name="revendedor"
    )
    provider = models.ForeignKey(
        AssistanceProvider,
        on_delete=models.PROTECT,
        related_name="plans",
        verbose_name="Proveedor permanente",
        help_text=PROVIDER_PERMANENCE,
    )
    name = models.CharField("nombre", max_length=200)
    internal_amount = models.DecimalField(
        "importe interno",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    currency = models.CharField(
        "moneda interna",
        max_length=3,
        default="MXN",
        validators=[RegexValidator(r"^[A-Z]{3}$", "Usa un código de moneda de tres letras.")],
    )
    availability = models.CharField(
        "disponibilidad",
        max_length=30,
        choices=Availability,
        default=Availability.ALL_BUSINESSES,
    )
    selected_businesses = models.ManyToManyField(
        Business,
        through="PlanBusinessAvailability",
        related_name="selected_plans",
        verbose_name="empresas seleccionadas",
    )
    created_at = models.DateTimeField("creado el", auto_now_add=True)

    class Meta:
        ordering = ("name", "pk")
        verbose_name = "Plan"
        verbose_name_plural = "Planes"
        constraints = [
            models.CheckConstraint(
                condition=Q(internal_amount__isnull=True) | Q(internal_amount__gte=0),
                name="ck_plan_nonnegative_amount",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("catalog:plan-detail", args=[self.pk])


class PlanBusinessAvailability(models.Model):
    plan = models.ForeignKey(
        Plan,
        on_delete=models.CASCADE,
        related_name="business_availabilities",
        verbose_name="Plan",
    )
    business = models.ForeignKey(
        Business,
        on_delete=models.PROTECT,
        related_name="plan_availabilities",
        verbose_name="empresa",
    )

    class Meta:
        ordering = ("business__name", "pk")
        verbose_name = "disponibilidad de Plan"
        verbose_name_plural = "disponibilidades de Plan"
        constraints = [
            models.UniqueConstraint(
                fields=("plan", "business"),
                name="uq_plan_business_availability",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.plan} — {self.business}"


class PlanVersion(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        PUBLISHED = "published", "Publicada"

    plan = models.ForeignKey(
        Plan, on_delete=models.PROTECT, related_name="versions", verbose_name="Plan"
    )
    number = models.PositiveIntegerField("versión")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="authored_plan_versions",
        verbose_name="autor",
    )
    status = models.CharField("estado", max_length=20, choices=Status, default=Status.DRAFT)
    effective_from = models.DateField("vigente desde")
    effective_until = models.DateField("vigente hasta (fecha exclusiva)")
    duration_months = models.PositiveIntegerField(
        "duración en meses calendario", validators=[MinValueValidator(1)]
    )
    coverage_terms = models.TextField("condiciones de cobertura")
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="published_plan_versions",
        verbose_name="publicada por",
        null=True,
        blank=True,
    )
    published_at = models.DateTimeField("publicada el", null=True, blank=True)
    created_at = models.DateTimeField("creada el", auto_now_add=True)

    class Meta:
        ordering = ("-number",)
        verbose_name = "versión de Plan"
        verbose_name_plural = "versiones de Plan"
        constraints = [
            models.UniqueConstraint(fields=("plan", "number"), name="uq_plan_version_number"),
            models.CheckConstraint(
                condition=Q(number__gt=0, duration_months__gt=0),
                name="ck_plan_version_positive_months_number",
            ),
            models.CheckConstraint(
                condition=Q(effective_until__gt=F("effective_from")),
                name="ck_plan_version_effective_dates",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="draft", published_by__isnull=True, published_at__isnull=True)
                    | (
                        Q(
                            status="published",
                            published_by__isnull=False,
                            published_at__isnull=False,
                        )
                        & ~Q(author=F("published_by"))
                    )
                ),
                name="ck_plan_version_two_person_publication",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.plan} — v{self.number}"

    def get_absolute_url(self) -> str:
        return reverse("catalog:version-detail", args=[self.pk])


class PlanService(models.Model):
    class ServiceChannel(models.TextChoices):
        ONLINE = "online", "En línea"
        CALL_CENTER = "call_center", "Centro de atención telefónica"

    version = models.ForeignKey(
        PlanVersion, on_delete=models.PROTECT, related_name="services", verbose_name="versión"
    )
    position = models.PositiveSmallIntegerField("posición")
    name = models.CharField("servicio para el Afiliado", max_length=200)
    coverage_terms = models.TextField("condiciones del servicio")
    service_channels = models.JSONField(
        "canales de servicio",
        validators=(validate_service_channels,),
    )
    limit_text = models.TextField("límites o condiciones para el Afiliado", blank=True)
    internal_notes = models.TextField("notas internas de atención", blank=True)
    public_description = models.TextField("descripción pública", blank=True)
    marketing_text = models.TextField("texto de marketing", blank=True)
    image_reference = models.CharField(
        "referencia de imagen",
        max_length=500,
        blank=True,
        validators=(validate_coverage_image_reference,),
    )
    presentation_visible = models.BooleanField("presentación visible", default=False)

    class Meta:
        ordering = ("position", "pk")
        verbose_name = "servicio de Plan"
        verbose_name_plural = "servicios de Plan"
        constraints = [
            models.CheckConstraint(
                condition=Q(position__gt=0),
                name="ck_plan_service_positive_position",
            ),
            models.UniqueConstraint(
                fields=("version", "position"),
                name="uq_plan_service_version_position",
            ),
            models.CheckConstraint(
                condition=Q(
                    service_channels__0__isnull=False,
                    service_channels__contained_by=[
                        "online",
                        "call_center",
                    ],
                ),
                name="ck_plan_service_supported_channels",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def service_channel_labels(self) -> list[str]:
        labels = dict(self.ServiceChannel.choices)
        return [labels[channel] for channel in self.service_channels]
