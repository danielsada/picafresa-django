from django.urls import path

from . import views

app_name = "enrollments"

urlpatterns = [
    path("<int:enrollment_id>/", views.enrollment_detail, name="detail"),
    path("<int:enrollment_id>/estado/", views.enrollment_transition, name="transition"),
    path("<int:enrollment_id>/renovar/", views.enrollment_renew, name="renew"),
]
