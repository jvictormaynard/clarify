from django.urls import include, path
from allauth.headless.constants import Client
from .service.accounts import ContinueWithEmailView
from .service.api import AccountView, DictionaryView, DictationView, UsageView, health

urlpatterns = [
    path("health", health),
    path(
        "_allauth/app/v1/auth/continue",
        ContinueWithEmailView.as_api_view(client=Client.APP),
    ),
    path("_allauth/", include("allauth.headless.urls")),
    path("v1/account", AccountView.as_view()),
    path("v1/usage", UsageView.as_view()),
    path("v1/dictionary", DictionaryView.as_view()),
    path("v1/dictations", DictationView.as_view()),
]
