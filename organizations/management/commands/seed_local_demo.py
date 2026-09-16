import json
import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from audit.services import record_privileged_event
from organizations.models import (
    AssistanceProvider,
    Business,
    ProviderAssignment,
    Reseller,
    ScopedAssignment,
)
from organizations.services import record_assignment_grant, record_organization_change

PORTFOLIOS = (
    ("Archers", "archers", ("M21", "HUC")),
    ("Carlos Asistencias", "carlos", ("Asistencias Centro", "Asistencias Norte")),
    ("Salubritas SA de CV", "salubritas", ("Clínica Centro Demo", "Clínica Sur Demo")),
    ("Pedro Beneficios", "pedro", ("Beneficios Centro", "Beneficios Norte")),
)
PROVIDERS = ("Asistencias Cuatro", "Asistencias MENOS")
SEED_ACTION = "demo.local_seeded"


def _demo_account(
    email: str, *, platform: bool = False, create: bool = True
) -> tuple[User, str | None]:
    user = User.objects.filter(email=email).first()
    if user is not None:
        if (
            not user.is_active
            or user.email_verified_at is None
            or user.is_superuser != platform
            or user.is_staff != platform
        ):
            raise CommandError(
                f"La cuenta {email} ya existe con otro estado o permisos; no se modificó."
            )
        return user, None
    if not create:
        raise CommandError(f"No se encontró la cuenta demo {email}; no se recreó.")
    password = secrets.token_urlsafe(16)
    user = User.objects.create_user(
        email=email,
        password=password,
        is_staff=platform,
        is_superuser=platform,
        email_verified_at=timezone.now(),
    )
    return user, password


def _check_permissions(user: User, reseller: Reseller) -> None:
    if (
        ScopedAssignment.objects.filter(user=user, revoked_at__isnull=True)
        .exclude(role=ScopedAssignment.Role.RESELLER_ADMIN, reseller=reseller)
        .exists()
    ):
        raise CommandError(f"La cuenta {user.email} tiene permisos para otras organizaciones.")


def _existing_credentials(operator: User, event: AuditEvent) -> list[dict[str, str | None]]:
    references = event.changes.get("resellers")
    if event.actor_id != operator.pk or not isinstance(references, dict):
        raise CommandError("El registro de datos demo no coincide con la cuenta de operador.")
    credentials: list[dict[str, str | None]] = [
        {"role": "Operador de plataforma", "email": operator.email, "password": None}
    ]
    for _, slug, _ in PORTFOLIOS:
        reseller_id = references.get(slug)
        if not isinstance(reseller_id, int):
            raise CommandError(
                "El registro de datos demo no tiene permisos para una cartera válida."
            )
        reseller = Reseller.objects.filter(pk=reseller_id).first()
        if reseller is None:
            raise CommandError("No se encontró una cartera demo; no se recreó.")
        user, _ = _demo_account(f"demo.{slug}@example.test", create=False)
        _check_permissions(user, reseller)
        credentials.append({"role": reseller.name, "email": user.email, "password": None})
    return credentials


class Command(BaseCommand):
    help = (
        "Crea datos ficticios para pruebas locales. Las contraseñas nuevas se muestran "
        "una sola vez; las cuentas y los datos existentes no se sobrescriben."
    )

    def handle(self, *args: str, **options: object) -> str:
        if settings.SETTINGS_MODULE != "config.settings.local":
            raise CommandError("Los datos demo solo se pueden crear con config.settings.local.")
        credentials: list[dict[str, str | None]] = []
        with transaction.atomic():
            operator, password = _demo_account("demo.operador@example.test", platform=True)
            operator = User.objects.select_for_update().get(pk=operator.pk)
            event = AuditEvent.objects.filter(action=SEED_ACTION).first()
            if event is not None:
                return json.dumps(
                    _existing_credentials(operator, event), ensure_ascii=False, indent=2
                )
            credentials.append(
                {"role": "Operador de plataforma", "email": operator.email, "password": password}
            )
            providers = []
            for provider_name in PROVIDERS:
                provider, created = AssistanceProvider.objects.get_or_create(
                    name=provider_name,
                    defaults={
                        "contact_name": "Mesa de ayuda ficticia",
                        "contact_email": "asistencia@example.test",
                        "service_instructions": (
                            "Datos ficticios para pruebas locales. No solicitar asistencia real."
                        ),
                    },
                )
                if created:
                    record_organization_change(
                        provider, operator, ["name", "contact_name", "contact_email"], created=True
                    )
                providers.append(provider)
            reseller_references: dict[str, int] = {}
            for name, slug, named_businesses in PORTFOLIOS:
                reseller, created = Reseller.objects.get_or_create(name=name)
                reseller_references[slug] = reseller.pk
                if created:
                    record_organization_change(reseller, operator, ["name"], created=True)
                user, password = _demo_account(f"demo.{slug}@example.test")
                _check_permissions(user, reseller)
                credentials.append({"role": name, "email": user.email, "password": password})
                if not ScopedAssignment.objects.filter(user=user, reseller=reseller).exists():
                    assignment = ScopedAssignment.objects.create(
                        user=user,
                        role=ScopedAssignment.Role.RESELLER_ADMIN,
                        reseller=reseller,
                        granted_by=operator,
                    )
                    record_assignment_grant(assignment, operator)
                business_names = (
                    *named_businesses,
                    *(f"Sucursal demo {index:02d}" for index in range(1, 22)),
                )
                for business_name in business_names:
                    business, created = Business.objects.get_or_create(
                        reseller=reseller, name=business_name
                    )
                    if created:
                        record_organization_change(
                            business, operator, ["name", "reseller"], created=True
                        )
                    for provider in providers:
                        relationship, created = ProviderAssignment.objects.get_or_create(
                            business=business,
                            provider=provider,
                            defaults={"contact_name_override": f"Contacto demo de {business_name}"},
                        )
                        if created:
                            record_organization_change(
                                relationship,
                                operator,
                                ["business", "provider", "contact_name_override"],
                                created=True,
                            )
            record_privileged_event(
                operator, SEED_ACTION, operator, {"resellers": reseller_references}
            )
        return json.dumps(credentials, ensure_ascii=False, indent=2)
