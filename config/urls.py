from django.contrib import admin
from django.urls import include, path

from accounts import views as account_views

urlpatterns = [
    path(
        "",
        account_views.AccountLoginView.as_view(),
        name="landing",
    ),
    path("cuenta/", account_views.home, name="account-home"),
    path("cuenta/activar/", account_views.activate, name="account-activate"),
    path(
        "cuenta/recuperar/",
        account_views.password_reset,
        name="password-reset",
    ),
    path(
        "cuenta/recuperar/enviado/",
        account_views.password_reset_sent,
        name="password-reset-sent",
    ),
    path(
        "cuenta/recuperar/confirmar/",
        account_views.password_reset_confirm,
        name="password-reset-confirm",
    ),
    path("cuenta/cambiar-correo/", account_views.email_change, name="email-change"),
    path(
        "cuenta/cambiar-correo/enviado/",
        account_views.email_change_sent,
        name="email-change-sent",
    ),
    path(
        "cuenta/cambiar-correo/confirmar/",
        account_views.email_change_confirm,
        name="email-change-confirm",
    ),
    path("cerrar-sesion/", account_views.logout_account, name="logout"),
    path("cartera/", include("organizations.urls")),
    path("planes/", include("catalog.urls")),
    path("admin/", admin.site.urls),
]
