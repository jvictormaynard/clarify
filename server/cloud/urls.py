from django.urls import include, path
from allauth.headless.constants import Client
from .service.accounts import ContinueWithEmailView
from .service import admin_views, social, transparency
from .service.api import (
    AccountView,
    DictionaryView,
    DictationView,
    HistorySyncView,
    SnippetView,
    TextView,
    TextActionsView,
    TextActionExecuteView,
    UsageView,
    health,
)

urlpatterns = [
    path("health", health),
    path("transparency/", transparency.page),
    path("transparency/assets/<str:name>", transparency.asset),
    path("v1/public/finances", transparency.summary),
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
    path("_allauth/app/v1/auth/social/start", social.start),
    path("_allauth/app/v1/auth/social/poll", social.poll),
    path("_allauth/app/v1/auth/social/cancel", social.cancel),
    path(
        "social/authorize/<uuid:attempt_id>/<slug:launch>/",
        social.authorize,
        name="social_authorize",
    ),
    path("social/complete/<str:client>/", social.finish, name="social_finish"),
    # These are the allauth provider callback URLs. Only the managed handoff
    # wrapper may enter them; no generic browser login/connect route is exposed.
    *[
        path(
            f"accounts/{provider}/login/callback/",
            social.callback,
            {"provider": provider},
            name=f"{provider}_callback",
        )
        for provider in ("google", "microsoft", "github")
    ],
    path("_allauth/", include("allauth.headless.urls")),
    path("v1/account", AccountView.as_view()),
    path("v1/usage", UsageView.as_view()),
    path("v1/dictionary", DictionaryView.as_view()),
    path("v1/snippets", SnippetView.as_view()),
    path("v1/history/sync", HistorySyncView.as_view()),
    path("v1/dictations", DictationView.as_view()),
    path("v1/text", TextView.as_view()),
    path("v1/text-actions", TextActionsView.as_view()),
    path("v1/text-actions/execute", TextActionExecuteView.as_view()),
]
