from django.urls import include, path
from allauth.headless.constants import Client
from .service.accounts import ContinueWithEmailView
from .service import admin_views
from .service.api import (
    AccountView,
    DictionaryView,
    DictationView,
    HistorySyncView,
    TextView,
    UsageView,
    health,
)

urlpatterns = [
    path("health", health),
    path("admin/", admin_views.dashboard),
    path("admin/assets/<str:name>", admin_views.asset),
    path("admin/api/session", admin_views.session),
    path("admin/api/logout", admin_views.sign_out),
    path("admin/api/overview", admin_views.overview),
    path("admin/api/users", admin_views.users),
    path("admin/api/users/<uuid:user_id>", admin_views.user_detail),
    path(
        "_allauth/browser/v1/auth/code/request",
        admin_views.AdminRequestLoginCodeView.as_api_view(client=Client.BROWSER),
    ),
    path(
        "_allauth/browser/v1/auth/code/confirm",
        admin_views.AdminConfirmLoginCodeView.as_api_view(client=Client.BROWSER),
    ),
    path(
        "_allauth/app/v1/auth/continue",
        ContinueWithEmailView.as_api_view(client=Client.APP),
    ),
    path("_allauth/", include("allauth.headless.urls")),
    path("v1/account", AccountView.as_view()),
    path("v1/usage", UsageView.as_view()),
    path("v1/dictionary", DictionaryView.as_view()),
    path("v1/history/sync", HistorySyncView.as_view()),
    path("v1/dictations", DictationView.as_view()),
    path("v1/text", TextView.as_view()),
]
