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
    # Third party
    "rest_framework",
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
# Demo convenience: quick-login buttons on the login page
# ---------------------------------------------------------------------------
DEMO_LOGINS = [
    {"role": "Admin", "username": "admin", "password": "admin123", "accent": "violet"},
    {"role": "Teacher", "username": "t.hasan", "password": "demo123", "accent": "emerald"},
    {"role": "Student", "username": "s.rahman", "password": "demo123", "accent": "sky"},
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
