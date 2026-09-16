from datetime import date
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from catalog.models import PlanVersion
from organizations.models import Business


class Member(models.Model):
    business = models.ForeignKey(
        Business,
        on_delete=models.PROTECT,
        related_name="members",
        verbose_name="empresa",
    )
    full_name = models.CharField("nombre completo", max_length=250)
    auto_renew_allowed = models.BooleanField("permite renovación automática", default=True)
    created_at = models.DateTimeField("creado el", auto_now_add=True)

    class Meta:
        ordering = ("full_name", "pk")
        verbose_name = "Afiliado"
        verbose_name_plural = "Afiliados"

    def __str__(self) -> str:
        return self.full_name


class PlanEnrollment(models.Model):
    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Pendiente de pago"
        ACTIVE = "active", "Activa"
        SUSPENDED = "suspended", "Suspendida"
        EXPIRED = "expired", "Vencida"
        CANCELLED = "cancelled", "Cancelada"

    member = models.ForeignKey(
        Member,
        on_delete=models.PROTECT,
        related_name="enrollments",
        verbose_name="Afiliado",
    )
    business = models.ForeignKey(
        Business,
        on_delete=models.PROTECT,
        related_name="plan_enrollments",
        verbose_name="empresa",
    )
    plan_version = models.ForeignKey(
        PlanVersion,
        on_delete=models.PROTECT,
        related_name="enrollments",
        verbose_name="versión de Plan",
    )
    preceding_enrollment = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        related_name="renewal",
        verbose_name="Póliza anterior",
        null=True,
        blank=True,
    )
    status = models.CharField(
        "estado",
        max_length=20,
        choices=Status,
        default=Status.PENDING_PAYMENT,
    )
    start_date = models.DateField("inicio")
    end_date = models.DateField("fin exclusivo")
    duration_months = models.PositiveIntegerField("duración en meses calendario")
    provider_contact_name = models.CharField("contacto del Proveedor", max_length=200, blank=True)
    provider_contact_email = models.EmailField("correo del Proveedor", blank=True)
    provider_contact_phone = models.CharField("teléfono del Proveedor", max_length=50, blank=True)
    provider_service_instructions = models.TextField("instrucciones del Proveedor", blank=True)
    override_reason = models.TextField("motivo de excepción", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_plan_enrollments",
        verbose_name="creada por",
    )
    created_at = models.DateTimeField("creada el", auto_now_add=True)

    IMMUTABLE_FIELDS = (
        "member_id",
        "business_id",
        "plan_version_id",
        "preceding_enrollment_id",
        "start_date",
        "end_date",
        "duration_months",
        "provider_contact_name",
        "provider_contact_email",
        "provider_contact_phone",
        "provider_service_instructions",
        "override_reason",
        "created_by_id",
    )

    class Meta:
        ordering = ("-start_date", "-pk")
        verbose_name = "Póliza"
        verbose_name_plural = "Pólizas"
        constraints = [
            models.CheckConstraint(
                condition=Q(duration_months__gt=0),
                name="ck_enrollment_positive_duration",
            ),
            models.CheckConstraint(
                condition=Q(end_date__gt=F("start_date")),
                name="ck_enrollment_effective_dates",
            ),
            models.CheckConstraint(
                condition=~Q(pk=F("preceding_enrollment")),
                name="ck_enrollment_not_self_preceding",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.member} — {self.start_date:%Y-%m-%d}"

    def covers(self, on_date: date) -> bool:
        return self.start_date <= on_date < self.end_date

    @property
    def plan_name(self) -> str:
        return self.plan_version.plan.name

    @property
    def provider_name(self) -> str:
        return self.plan_version.plan.provider.name

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk:
            persisted = type(self).objects.filter(pk=self.pk).values(*self.IMMUTABLE_FIELDS).first()
            if persisted is not None and any(
                persisted[field] != getattr(self, field) for field in self.IMMUTABLE_FIELDS
            ):
                raise ValidationError("Los términos de una Póliza son inmutables.")
        super().save(*args, **kwargs)


# Create your models here.
