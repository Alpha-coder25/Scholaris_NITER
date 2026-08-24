"""
Django settings for Scholaris.

Designed to work with zero external services out of the box:
  * Database:  PostgreSQL via Neon if DATABASE_URL is set, otherwise SQLite.
  * AI:        Anthropic API if ANTHROPIC_API_KEY is set, otherwise a built-in
               offline question generator (see ai_integration/services.py).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env(key, default=None):
    return os.environ.get(key, default)


# ---------------------------------------------------------------------------
# Core Django
# ---------------------------------------------------------------------------
SECRET_KEY = env("SECRET_KEY", "django-insecure-scholaris-hackathon-dev-key")

DEBUG = env("DEBUG", "1") == "1"

# .vercel.app included by default so Vercel preview + production URLs work
# without extra configuration.
ALLOWED_HOSTS = [
    h.strip()
    for h in env("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver,.vercel.app").split(",")
    if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Third party
    "rest_framework",
    "storages",
    # Scholaris apps
    "accounts",
    "academics",
    "materials",
    "exams",
    "ratings",
    "ai_integration",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "scholaris.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "scholaris.context_processors.site_globals",
            ],
        },
    },
]

WSGI_APPLICATION = "scholaris.wsgi.application"
ASGI_APPLICATION = "scholaris.asgi.application"

# ---------------------------------------------------------------------------
# Database — Neon (Postgres) via DATABASE_URL, SQLite fallback for zero-setup dev
# ---------------------------------------------------------------------------
DATABASE_URL = env("DATABASE_URL")
if DATABASE_URL:
    import dj_database_url

    # Neon free tier: use the *pooled* connection string (hostname contains
    # "-pooler") and don't hold persistent connections (conn_max_age=0) so the
    # strict free-tier connection cap is never exhausted.
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=0,
            ssl_require=True,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ---------------------------------------------------------------------------
# Auth — custom User with role field
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 6}},
]

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"  # land back on the public landing page after logout

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Dhaka"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static & media
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---------------------------------------------------------------------------
# Cloud storage (AWS S3 / S3-compatible) for file uploads in production.
# When AWS_STORAGE_BUCKET_NAME is set, files are stored on S3; otherwise the
# local MEDIA_ROOT filesystem is used (fine for development).
# ---------------------------------------------------------------------------
AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY", "")
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", "")
AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", "us-east-1")
AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", "")
AWS_S3_CUSTOM_DOMAIN = env("AWS_S3_CUSTOM_DOMAIN", "")
AWS_S3_FILE_OVERWRITE = False
AWS_DEFAULT_ACL = None  # Use bucket default (private)
AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "max-age=86400"}

if AWS_STORAGE_BUCKET_NAME and AWS_ACCESS_KEY_ID:
    DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
    # Public-read ACL for course materials so students can download them.
    # Override the default storage to serve files publicly.
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
            "OPTIONS": {
                "acl": "public-read",
            },
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }
    if AWS_S3_CUSTOM_DOMAIN:
        MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/media/"
    else:
        MEDIA_URL = f"https://{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com/media/"
else:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

# ---------------------------------------------------------------------------
# DRF (used for the JSON exam-take API)
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# ---------------------------------------------------------------------------
# External services
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", "")
AI_MODEL = env("AI_MODEL", "claude-sonnet-4-5")
# Minimum number of ratings before an aggregate is revealed (privacy by design)
RATING_MIN_RESPONSES = int(env("RATING_MIN_RESPONSES", "3"))

# ---------------------------------------------------------------------------
# Email — console backend by default (offline dev), configurable for production
# ---------------------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_USE_TLS = env("EMAIL_USE_TLS", "1") == "1"
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "Scholaris <noreply@scholaris.niter.edu.bd>")

# AI notifications — auto-notify students with critically weak topics after grading
AI_NOTIFY_WEAK_TOPICS = env("AI_NOTIFY_WEAK_TOPICS", "1") == "1"
AI_WEAK_TOPIC_THRESHOLD = int(env("AI_WEAK_TOPIC_THRESHOLD", "30"))  # accuracy % below which a notification fires

# ---------------------------------------------------------------------------
# Production (Vercel) hardening — activated by setting DEBUG=0
# ---------------------------------------------------------------------------
if not DEBUG:
    # Vercel terminates TLS; trust its forwarded scheme header so Django
    # generates https links and treats requests correctly. (Same-origin POSTs
    # need no CSRF_TRUSTED_ORIGINS; wildcards are unsupported there.)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# ---------------------------------------------------------------------------
# Demo data seeding
# ---------------------------------------------------------------------------
# Password used for every account created by `seed_demo_data`. If unset, each
# seeded user gets a strong random password that is printed once at seed time.
# There are no published demo credentials and no one-click demo login.
SEED_PASSWORD = env("SEED_PASSWORD", "")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
