from typing import Any

from django.conf import settings
from django.db import models
from django.utils import timezone

from .context import current_correlation_id


class AppendOnlyAuditQuerySet(models.QuerySet["AuditEvent"]):
    def update(self, **kwargs: Any) -> int:
        del kwargs
        raise ValueError("Los eventos de auditoría son inmutables.")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise ValueError("Los eventos de auditoría son inmutables.")


class AuditEventManager(models.Manager["AuditEvent"]):
    def get_queryset(self) -> AppendOnlyAuditQuerySet:
        return AppendOnlyAuditQuerySet(self.model, using=self._db)


class AuditEvent(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    action = models.CharField(max_length=100)
    object_type = models.CharField(max_length=100)
    object_reference = models.CharField(max_length=100)
    correlation_id = models.UUIDField(default=current_correlation_id)
    changes = models.JSONField(default=dict)
    occurred_at = models.DateTimeField(default=timezone.now)

    objects = AuditEventManager()

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValueError("Los eventos de auditoría son inmutables.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        del args, kwargs
        raise ValueError("Los eventos de auditoría son inmutables.")
