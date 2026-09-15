from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


def validate_iana_timezone(value: str) -> None:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise ValidationError("Escribe una zona horaria IANA válida.") from error


class OrganizationLifecycle(models.Model):
    is_active = models.BooleanField("activo", default=True)
    deleted_at = models.DateTimeField("eliminado el", null=True, blank=True)
    created_at = models.DateTimeField("creado el", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado el", auto_now=True)

    class Meta:
        abstract = True


class Reseller(OrganizationLifecycle):
    name = models.CharField("nombre", max_length=200, unique=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "revendedor"
        verbose_name_plural = "revendedores"

    def __str__(self) -> str:
        return self.name


class Business(OrganizationLifecycle):
    reseller = models.ForeignKey(
        Reseller,
        on_delete=models.PROTECT,
        related_name="businesses",
        verbose_name="revendedor",
    )
    name = models.CharField("nombre", max_length=200)
    timezone = models.CharField(
        "zona horaria",
        max_length=100,
        default="America/Mexico_City",
        validators=(validate_iana_timezone,),
    )

    class Meta:
        ordering = ("name",)
        verbose_name = "empresa"
        verbose_name_plural = "empresas"
        constraints = [
            models.UniqueConstraint(
                fields=("reseller", "name"),
                name="uq_business_reseller_name",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class AssistanceProvider(OrganizationLifecycle):
    name = models.CharField("nombre", max_length=200, unique=True)
    contact_name = models.CharField("nombre de contacto", max_length=200, blank=True)
    contact_email = models.EmailField("correo de contacto", blank=True)
    contact_phone = models.CharField("teléfono de contacto", max_length=50, blank=True)
    service_instructions = models.TextField("instrucciones de servicio", blank=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "proveedor de asistencia"
        verbose_name_plural = "proveedores de asistencia"

    def __str__(self) -> str:
        return self.name


class ProviderAssignment(OrganizationLifecycle):
    business = models.ForeignKey(
        Business,
        on_delete=models.PROTECT,
        related_name="provider_assignments",
        verbose_name="empresa",
    )
    provider = models.ForeignKey(
        AssistanceProvider,
        on_delete=models.PROTECT,
        related_name="business_assignments",
        verbose_name="proveedor",
    )
    contact_name_override = models.CharField(
        "nombre de contacto específico",
        max_length=200,
        blank=True,
    )
    contact_email_override = models.EmailField("correo de contacto específico", blank=True)
    contact_phone_override = models.CharField(
        "teléfono de contacto específico",
        max_length=50,
        blank=True,
    )
    service_instructions_override = models.TextField(
        "instrucciones de servicio específicas",
        blank=True,
    )

    class Meta:
        ordering = ("business__name", "provider__name")
        verbose_name = "asignación de proveedor"
        verbose_name_plural = "asignaciones de proveedores"
        constraints = [
            models.UniqueConstraint(
                fields=("business", "provider"),
                name="uq_provider_assignment_business_provider",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.provider} — {self.business}"

    @property
    def effective_contact_name(self) -> str:
        return self.contact_name_override or self.provider.contact_name

    @property
    def effective_contact_email(self) -> str:
        return self.contact_email_override or self.provider.contact_email

    @property
    def effective_contact_phone(self) -> str:
        return self.contact_phone_override or self.provider.contact_phone

    @property
    def effective_service_instructions(self) -> str:
        return self.service_instructions_override or self.provider.service_instructions


class ScopedAssignment(models.Model):
    class Role(models.TextChoices):
        RESELLER_ADMIN = "reseller_admin", "Administrador de revendedor"
        PROVIDER_EMPLOYEE = "provider_employee", "Empleado de proveedor"
        TENANT_ADMIN = "tenant_admin", "Administrador de empresa"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="scoped_assignments",
        verbose_name="usuario",
    )
    role = models.CharField("rol", max_length=30, choices=Role)
    reseller = models.ForeignKey(
        Reseller,
        on_delete=models.PROTECT,
        related_name="user_assignments",
        verbose_name="revendedor",
        null=True,
        blank=True,
    )
    provider_assignment = models.ForeignKey(
        ProviderAssignment,
        on_delete=models.PROTECT,
        related_name="user_assignments",
        verbose_name="contexto de proveedor y empresa",
        null=True,
        blank=True,
    )
    business = models.ForeignKey(
        Business,
        on_delete=models.PROTECT,
        related_name="user_assignments",
        verbose_name="empresa",
        null=True,
        blank=True,
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="granted_scoped_assignments",
        verbose_name="otorgado por",
        null=True,
        blank=True,
    )
    revoked_at = models.DateTimeField("revocado el", null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="revoked_scoped_assignments",
        verbose_name="revocado por",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField("creado el", auto_now_add=True)

    class Meta:
        ordering = ("user__email", "role")
        verbose_name = "asignación de alcance"
        verbose_name_plural = "asignaciones de alcance"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        role="reseller_admin",
                        reseller__isnull=False,
                        provider_assignment__isnull=True,
                        business__isnull=True,
                    )
                    | Q(
                        role="provider_employee",
                        reseller__isnull=True,
                        provider_assignment__isnull=False,
                        business__isnull=True,
                    )
                    | Q(
                        role="tenant_admin",
                        reseller__isnull=True,
                        provider_assignment__isnull=True,
                        business__isnull=False,
                    )
                ),
                name="ck_scoped_assignment_matching_scope",
            ),
            models.UniqueConstraint(
                fields=("user", "reseller"),
                condition=Q(reseller__isnull=False, revoked_at__isnull=True),
                name="uq_scoped_assignment_user_reseller",
            ),
            models.UniqueConstraint(
                fields=("user", "provider_assignment"),
                condition=Q(provider_assignment__isnull=False, revoked_at__isnull=True),
                name="uq_scoped_assignment_user_provider",
            ),
            models.UniqueConstraint(
                fields=("user", "business"),
                condition=Q(business__isnull=False, revoked_at__isnull=True),
                name="uq_scoped_assignment_user_business",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} — {self.get_role_display()}"
