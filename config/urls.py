from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

urlpatterns = [
    path(
        "",
        LoginView.as_view(
            template_name="registration/login.html",
            redirect_authenticated_user=True,
        ),
        name="landing",
    ),
    path("cerrar-sesion/", LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
]
