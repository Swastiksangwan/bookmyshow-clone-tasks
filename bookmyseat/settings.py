"""
Django settings for the BookMySeat project.

Local development:
- SQLite database
- DEBUG=True
- Console email backend

Production deployment:
- PostgreSQL through DATABASE_URL
- DEBUG=False
- WhiteNoise static-file serving
- Secure environment-based configuration
"""

import os
from pathlib import Path
from urllib.parse import urlparse

import django
import dj_database_url
from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------

def env_bool(name, default=False):
    """Read a boolean environment variable safely."""
    value = os.environ.get(name)

    if value is None:
        return default

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def env_list(name, default=""):
    """Read a comma-separated environment variable as a clean list."""
    value = os.environ.get(name, default)

    return [
        item.strip()
        for item in value.split(",")
        if item.strip()
    ]


def normalize_host(value):
    """
    Convert a hostname or full URL into a hostname suitable for
    ALLOWED_HOSTS.
    """
    value = value.strip().rstrip("/")

    if "://" in value:
        return urlparse(value).netloc

    return value


# ---------------------------------------------------------------------
# Core security settings
# ---------------------------------------------------------------------

DEBUG = env_bool("DEBUG", True)

LOCAL_SECRET_KEY = (
    "django-insecure-local-development-key-change-before-production"
)

SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    LOCAL_SECRET_KEY,
)

# Never allow production to start with the development fallback key.
if not DEBUG and SECRET_KEY == LOCAL_SECRET_KEY:
    raise ImproperlyConfigured(
        "SECRET_KEY must be configured when DEBUG=False."
    )


allowed_hosts = [
    "127.0.0.1",
    "localhost",
]

allowed_hosts.extend(
    normalize_host(host)
    for host in env_list("ALLOWED_HOSTS")
)

# Render automatically provides this environment variable.
RENDER_EXTERNAL_HOSTNAME = os.environ.get(
    "RENDER_EXTERNAL_HOSTNAME",
    "",
).strip()

if RENDER_EXTERNAL_HOSTNAME:
    allowed_hosts.append(
        normalize_host(RENDER_EXTERNAL_HOSTNAME)
    )

# Remove empty and duplicate values while keeping order.
ALLOWED_HOSTS = list(
    dict.fromkeys(
        host
        for host in allowed_hosts
        if host
    )
)


# Django 4+ requires URL schemes in CSRF_TRUSTED_ORIGINS.
# Django 3.2 expects hostnames without schemes.
csrf_origin_values = env_list("CSRF_TRUSTED_ORIGINS")

if RENDER_EXTERNAL_HOSTNAME:
    csrf_origin_values.append(
        RENDER_EXTERNAL_HOSTNAME
    )

if django.VERSION >= (4, 0):
    CSRF_TRUSTED_ORIGINS = [
        origin
        if origin.startswith(("http://", "https://"))
        else f"https://{origin}"
        for origin in csrf_origin_values
    ]
else:
    CSRF_TRUSTED_ORIGINS = [
        origin.split("://", 1)[-1]
        for origin in csrf_origin_values
    ]

CSRF_TRUSTED_ORIGINS = list(
    dict.fromkeys(CSRF_TRUSTED_ORIGINS)
)


# Render terminates HTTPS at its reverse proxy.
SECURE_PROXY_SSL_HEADER = (
    "HTTP_X_FORWARDED_PROTO",
    "https",
)

if DEBUG:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_HSTS_SECONDS = 0
else:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    SECURE_HSTS_SECONDS = int(
        os.environ.get(
            "SECURE_HSTS_SECONDS",
            "3600",
        )
    )
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = False

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"


# ---------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "users",
    "movies",
]


# ---------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",

    # Must be directly after SecurityMiddleware.
    "whitenoise.middleware.WhiteNoiseMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


ROOT_URLCONF = "bookmyseat.urls"

WSGI_APPLICATION = "bookmyseat.wsgi.application"

LOGIN_URL = "/login/"


# The project uses Django's built-in user model.
AUTH_USER_MODEL = "auth.User"


# ---------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------

TEMPLATES = [
    {
        "BACKEND": (
            "django.template.backends.django."
            "DjangoTemplates"
        ),
        "DIRS": [
            BASE_DIR / "templates",
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                (
                    "django.template.context_processors."
                    "debug"
                ),
                (
                    "django.template.context_processors."
                    "request"
                ),
                (
                    "django.contrib.auth."
                    "context_processors.auth"
                ),
                (
                    "django.contrib.messages."
                    "context_processors.messages"
                ),
            ],
        },
    },
]


# ---------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "",
).strip()

if DATABASE_URL:
    # Production: PostgreSQL through Render DATABASE_URL.
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
        )
    }
else:
    # Local development and automated tests.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# ---------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------

# Suitable for local development and a single Gunicorn worker.
# Use Redis for shared caching across multiple production workers.
CACHES = {
    "default": {
        "BACKEND": (
            "django.core.cache.backends."
            "locmem.LocMemCache"
        ),
        "LOCATION": "bookmyseat-admin-analytics",
    }
}


# ---------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        ),
    },
]


# ---------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# ---------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------

STATIC_URL = "/static/"

# Source static assets committed with the project.
STATICFILES_DIRS = [
    BASE_DIR / "static",
]

# collectstatic writes production assets here.
STATIC_ROOT = BASE_DIR / "staticfiles"


# Django 4.2+ uses STORAGES.
# Older supported project environments use STATICFILES_STORAGE.
STATICFILES_STORAGE_BACKEND = (
    "django.contrib.staticfiles.storage.StaticFilesStorage"
    if DEBUG
    else "whitenoise.storage.CompressedManifestStaticFilesStorage"
)

if django.VERSION >= (4, 2):
    STORAGES = {
        "default": {
            "BACKEND": (
                "django.core.files.storage."
                "FileSystemStorage"
            ),
        },
        "staticfiles": {
            "BACKEND": STATICFILES_STORAGE_BACKEND,
        },
    }
else:
    STATICFILES_STORAGE = STATICFILES_STORAGE_BACKEND

# Tests and local runs may reference new static assets before collectstatic
# has generated a manifest. Deployment still runs collectstatic in build.sh.
WHITENOISE_MANIFEST_STRICT = False


# ---------------------------------------------------------------------
# Uploaded media
# ---------------------------------------------------------------------

MEDIA_URL = "/media/"

MEDIA_ROOT = BASE_DIR / "media"


# ---------------------------------------------------------------------
# Email configuration
# ---------------------------------------------------------------------

# Local default prints emails to the terminal.
# Production should configure SMTP or a transactional provider.
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)

EMAIL_HOST = os.environ.get(
    "EMAIL_HOST",
    "",
)

EMAIL_PORT = int(
    os.environ.get(
        "EMAIL_PORT",
        "587",
    )
)

EMAIL_USE_TLS = env_bool(
    "EMAIL_USE_TLS",
    True,
)

EMAIL_USE_SSL = env_bool(
    "EMAIL_USE_SSL",
    False,
)

if EMAIL_USE_TLS and EMAIL_USE_SSL:
    raise ImproperlyConfigured(
        "EMAIL_USE_TLS and EMAIL_USE_SSL "
        "cannot both be enabled."
    )

EMAIL_HOST_USER = os.environ.get(
    "EMAIL_HOST_USER",
    "",
)

EMAIL_HOST_PASSWORD = os.environ.get(
    "EMAIL_HOST_PASSWORD",
    "",
)

DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL",
    "BookMySeat <noreply@localhost>",
)


# ---------------------------------------------------------------------
# Razorpay configuration
# ---------------------------------------------------------------------

RAZORPAY_KEY_ID = os.environ.get(
    "RAZORPAY_KEY_ID",
    "",
)

RAZORPAY_KEY_SECRET = os.environ.get(
    "RAZORPAY_KEY_SECRET",
    "",
)

RAZORPAY_WEBHOOK_SECRET = os.environ.get(
    "RAZORPAY_WEBHOOK_SECRET",
    "",
)

TICKET_PRICE_PAISE = int(
    os.environ.get(
        "TICKET_PRICE_PAISE",
        "20000",
    )
)

PAYMENT_CURRENCY = os.environ.get(
    "PAYMENT_CURRENCY",
    "INR",
)


# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------

LOG_LEVEL = os.environ.get(
    "LOG_LEVEL",
    "INFO",
).upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": (
                "{levelname} {asctime} "
                "{name}: {message}"
            ),
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {
        "handlers": [
            "console",
        ],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": [
                "console",
            ],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "movies": {
            "handlers": [
                "console",
            ],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}


# ---------------------------------------------------------------------
# Default model primary key type
# ---------------------------------------------------------------------

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
