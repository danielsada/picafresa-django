from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("", views.plan_list, name="plan-list"),
    path("nuevo/", views.plan_edit, name="plan-create"),
    path("<int:plan_id>/", views.plan_detail, name="plan-detail"),
    path("<int:plan_id>/editar/", views.plan_edit, name="plan-edit"),
    path("<int:plan_id>/versiones/nueva/", views.draft_edit, name="draft-create"),
    path("versiones/<int:version_id>/", views.version_detail, name="version-detail"),
    path("versiones/<int:version_id>/editar/", views.draft_edit, name="draft-edit"),
    path("versiones/<int:version_id>/publicar/", views.version_publish, name="version-publish"),
]
