from django.urls import path

from enrollments import views as enrollment_views

from . import views

app_name = "organizations"

urlpatterns = [
    path("", views.portfolio, name="portfolio"),
    path("empresas/<int:business_id>/", views.business_detail, name="business-detail"),
    path("empresas/<int:business_id>/editar/", views.business_edit, name="business-edit"),
    path(
        "empresas/<int:business_id>/polizas/nueva/",
        enrollment_views.enrollment_create,
        name="enrollment-create",
    ),
    path(
        "empresas/<int:business_id>/proveedores/nuevo/",
        views.provider_contract_create,
        name="provider-contract-create",
    ),
    path(
        "empresas/<int:business_id>/proveedores/<int:relationship_id>/editar/",
        views.provider_edit,
        name="provider-edit",
    ),
    path(
        "empresas/<int:business_id>/proveedores/<int:relationship_id>/desactivar/",
        views.provider_contract_deactivate,
        name="provider-contract-deactivate",
    ),
]
