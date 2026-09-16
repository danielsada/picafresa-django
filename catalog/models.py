from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Q
from django.urls import reverse

from organizations.models import AssistanceProvider, Reseller

PROVIDER_PERMANENCE = (
    "El Proveedor es permanente. Para cambiarlo debes crear un nuevo Plan; "
    "las versiones anteriores conservan su Proveedor."
)


class Plan(models.Model):
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
    version = models.ForeignKey(
        PlanVersion, on_delete=models.PROTECT, related_name="services", verbose_name="versión"
    )
    name = models.CharField("servicio para el Afiliado", max_length=200)
    coverage_terms = models.TextField("condiciones del servicio")

    class Meta:
        ordering = ("pk",)
        verbose_name = "servicio de Plan"
        verbose_name_plural = "servicios de Plan"

    def __str__(self) -> str:
        return self.name
