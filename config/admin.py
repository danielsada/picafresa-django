from django.contrib.admin import AdminSite
from django.http import HttpRequest


class PlatformAdminSite(AdminSite):
    site_header = "Operación de Picafresa"
    site_title = "Operación de Picafresa"
    index_title = "Administración de plataforma"

    def has_permission(self, request: HttpRequest) -> bool:
        return request.user.is_active and request.user.is_superuser
