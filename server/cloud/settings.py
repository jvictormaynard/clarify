"""Fail-closed server configuration. No application profile is imported."""

import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit, unquote

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parents[1]
DEVELOPMENT = os.environ.get("CLARIFY_DEVELOPMENT") == "1"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEVELOPMENT:
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY in the server secret store")
    SECRET_KEY = "development-only-never-use-this-key-in-production"
DEBUG = False
ALLOWED_HOSTS = os.environ.get(
    "ALLOWED_HOSTS", "localhost,127.0.0.1,testserver" if DEVELOPMENT else ""
).split(",")
ROOT_URLCONF = "cloud.urls"
WSGI_APPLICATION = "cloud.wsgi.application"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "allauth",
    "allauth.account",
    "allauth.headless",
    "rest_framework",
    "cloud.service",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "cloud.service.middleware.RequestLimits",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]
AUTH_USER_MODEL = "service.User"
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
db_url = os.environ.get("DATABASE_URL", "")
if db_url:
    db = urlsplit(db_url)
    if db.scheme not in {"postgres", "postgresql"}:
        raise ImproperlyConfigured("Production requires PostgreSQL")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(db.path[1:]),
            "USER": unquote(db.username or ""),
            "PASSWORD": unquote(db.password or ""),
            "HOST": db.hostname,
            "PORT": db.port or 5432,
            "CONN_MAX_AGE": 60,
        }
    }
elif DEVELOPMENT:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / ".development.sqlite3",
        }
    }
else:
    raise ImproperlyConfigured("Set DATABASE_URL for a dedicated PostgreSQL database")
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "pt-br"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
            ]
        },
    }
]
HEADLESS_ONLY = True
HEADLESS_CLIENTS = ("app",)
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_EMAIL_VERIFICATION_BY_CODE_ENABLED = True
ACCOUNT_EMAIL_VERIFICATION_BY_CODE_TIMEOUT = 600
ACCOUNT_EMAIL_VERIFICATION_BY_CODE_FORMAT = {
    "numeric": True,
    "length": 6,
    "dashed": False,
}
ACCOUNT_LOGIN_BY_CODE_ENABLED = True
ACCOUNT_LOGIN_BY_CODE_TIMEOUT = 600
ACCOUNT_LOGIN_BY_CODE_FORMAT = {"numeric": True, "length": 6, "dashed": False}
ACCOUNT_LOGIN_BY_CODE_MAX_ATTEMPTS = 5
ACCOUNT_EMAIL_VERIFICATION_BY_CODE_MAX_ATTEMPTS = 5
ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_PREVENT_ENUMERATION = True
ACCOUNT_ADAPTER = "cloud.service.accounts.AccountAdapter"
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
SESSION_COOKIE_SECURE = not DEVELOPMENT
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = not DEVELOPMENT
SECURE_SSL_REDIRECT = not DEVELOPMENT
SECURE_REDIRECT_EXEMPT = [r"^health$"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 3600 if not DEVELOPMENT else 0
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
# allauth limits use the database cache, in addition to the atomic outer limiter.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "cloud_cache",
    }
}
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("SMTP_HOST", "")
EMAIL_PORT = int(os.environ.get("SMTP_PORT", "465"))
EMAIL_USE_SSL = os.environ.get("SMTP_SECURITY", "ssl") == "ssl"
EMAIL_USE_TLS = os.environ.get("SMTP_SECURITY", "ssl") == "starttls"
EMAIL_TIMEOUT = 10
EMAIL_HOST_USER = os.environ.get("SMTP_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("SMTP_FROM", "")
if DEVELOPMENT:
    EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "allauth.headless.contrib.rest_framework.authentication.XSessionTokenAuthentication"
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "EXCEPTION_HANDLER": "cloud.service.api.exception_handler",
}
DATA_UPLOAD_MAX_MEMORY_SIZE = 512 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 0
FILE_UPLOAD_HANDLERS = [
    "cloud.service.middleware.BoundedUpload",
    "django.core.files.uploadhandler.TemporaryFileUploadHandler",
]
DATA_UPLOAD_MAX_NUMBER_FIELDS = 8
DATA_UPLOAD_MAX_NUMBER_FILES = 1
CLARIFY_GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
CLARIFY_MONTHLY_AUDIO_MS = int(os.environ.get("CLARIFY_MONTHLY_AUDIO_MS", "18000000"))
CLARIFY_MONTHLY_BUDGET_USD = os.environ.get("CLARIFY_MONTHLY_BUDGET_USD", "0")
CLARIFY_GLOBAL_CONCURRENCY = int(os.environ.get("CLARIFY_GLOBAL_CONCURRENCY", "4"))
CLARIFY_SIGNUP_ENABLED = os.environ.get("CLARIFY_SIGNUP_ENABLED") == "1"
CLARIFY_DAILY_EMAIL_LIMIT = int(os.environ.get("CLARIFY_DAILY_EMAIL_LIMIT", "50"))
CLARIFY_FUNDED_ENABLED = os.environ.get("CLARIFY_FUNDED_ENABLED") == "1"
CLARIFY_MAX_UPLOAD_BYTES = 24 * 1024 * 1024
if not DEVELOPMENT:
    if len(SECRET_KEY) < 50 or not any(ALLOWED_HOSTS) or "*" in ALLOWED_HOSTS:
        raise ImproperlyConfigured(
            "Use a random secret of at least 50 characters and explicit ALLOWED_HOSTS"
        )
    if not all(
        (EMAIL_HOST, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, DEFAULT_FROM_EMAIL)
    ) or not (EMAIL_USE_SSL or EMAIL_USE_TLS):
        raise ImproperlyConfigured(
            "Configure authenticated SMTP with TLS before starting the account service"
        )
try:
    _budget = Decimal(CLARIFY_MONTHLY_BUDGET_USD)
    if not _budget.is_finite() or _budget < 0 or _budget > 100000:
        raise ValueError()
except (InvalidOperation, ValueError):
    raise ImproperlyConfigured("Set a finite, nonnegative monthly USD budget") from None
if CLARIFY_FUNDED_ENABLED and (not CLARIFY_GROQ_KEY or _budget <= 0):
    raise ImproperlyConfigured(
        "Funded processing requires a server Groq key and a positive budget"
    )
if (
    not 1 <= CLARIFY_GLOBAL_CONCURRENCY <= 32
    or not 0 <= CLARIFY_DAILY_EMAIL_LIMIT <= 100000
    or not 0 <= CLARIFY_MONTHLY_AUDIO_MS <= 3600000000
):
    raise ImproperlyConfigured("Invalid concurrency or account audio limit")
# Never log provider request/response bodies or HTTP headers.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "loggers": {"django.request": {"handlers": ["null"], "propagate": False}},
}
