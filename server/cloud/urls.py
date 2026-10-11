from django.urls import include, path
from .service.api import AccountView, DictionaryView, DictationView, UsageView, health

urlpatterns = [
    path("health", health),
    path("_allauth/", include("allauth.headless.urls")),
    path("v1/account", AccountView.as_view()),
    path("v1/usage", UsageView.as_view()),
    path("v1/dictionary", DictionaryView.as_view()),
    path("v1/dictations", DictationView.as_view()),
]
