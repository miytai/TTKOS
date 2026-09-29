"""Базовые настройки ForumOS.

Общие настройки для всех окружений. Переопределения — в dev.py / test.py / prod.py.
Все секреты приходят из окружения (TECHSPEC §15.9).
"""

import logging
from datetime import timedelta
from pathlib import Path

import environ
import structlog

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_SECRET_KEY=(str, ""),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    LOG_LEVEL=(str, "INFO"),
    APP_VERSION=(str, "1.0.0"),
    APP_HOST=(str, "http://localhost:8080"),
    SENTRY_DSN=(str, ""),
)

ENV_FILE = BASE_DIR.parent / ".env"
if ENV_FILE.exists():
    environ.Env.read_env(str(ENV_FILE))

# ── Ядро ────────────────────────────────────────────────────────────
SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    # Сторонние
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "corsheaders",
    "drf_spectacular",
    # Приложения ForumOS
    "apps.core",
    "apps.accounts",
    "apps.forums",
    "apps.threads",
    "apps.posts",
    "apps.reactions",
    "apps.notifications",
    "apps.moderation",
    "apps.analytics",
    "apps.search",
    "apps.seo",
    # Инфраструктурные
    "events",
    "shared",
]

MIDDLEWARE = [
    "shared.middleware.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "shared.middleware.AccessLogMiddleware",
    "shared.health.MetricsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

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
            ],
        },
    },
]

# ── База данных ─────────────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", default="forumos"),
        "USER": env("POSTGRES_USER", default="forumos"),
        "PASSWORD": env("POSTGRES_PASSWORD", default=""),
        "HOST": env("POSTGRES_HOST", default="localhost"),
        "PORT": env("POSTGRES_PORT", default="5432"),
        "CONN_MAX_AGE": env.int("POSTGRES_CONN_MAX_AGE", default=60),
        "OPTIONS": {
            "connect_timeout": 10,
        },
        "TEST": {"NAME": env("POSTGRES_TEST_DB", default="test_forumos")},
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Аутентификация ──────────────────────────────────────────────────
AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Argon2 — при наличии пакета, иначе PBKDF2 (TECHSPEC §4.1)
try:  # pragma: no cover - зависит от окружения
    import argon2  # noqa: F401

    PASSWORD_HASHERS = [
        "django.contrib.auth.hashers.Argon2PasswordHasher",
        "django.contrib.auth.hashers.PBKDF2PasswordHasher",
        "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    ]
except ImportError:  # pragma: no cover
    PASSWORD_HASHERS = [
        "django.contrib.auth.hashers.PBKDF2PasswordHasher",
        "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    ]

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_TTL_MINUTES", default=15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_TTL_DAYS", default=7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": env("JWT_SIGNING_KEY", default=SECRET_KEY),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# Кастомная аутентификация: access в Bearer-заголовке, refresh — в httpOnly-cookie
AUTHENTICATION_BACKENDS = [
    "apps.accounts.backends.EmailOrUsernameBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# ── DRF ─────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "shared.authentication.CookieJWTAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticatedOrReadOnly",),
    "DEFAULT_PAGINATION_CLASS": "shared.pagination.CursorPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
        "rest_framework.filters.SearchFilter",
    ),
    "DEFAULT_THROTTLE_CLASSES": (
        "shared.throttling.AnonRateThrottle",
        "shared.throttling.UserRateThrottle",
        "shared.throttling.ContentCreationThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("RATE_LIMIT_ANON", default="100/min"),
        "user": env("RATE_LIMIT_USER", default="60/min"),
        "content": env("RATE_LIMIT_CONTENT", default="30/min"),
        "login": env("RATE_LIMIT_LOGIN", default="10/min"),
        "register": env("RATE_LIMIT_REGISTER", default="3/hour"),
        "email": env("RATE_LIMIT_EMAIL", default="3/hour"),
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "shared.exceptions.api_exception_handler",
    "DEFAULT_RENDERER_CLASSES": ("shared.renderers.EnvelopeJSONRenderer",),
    "DEFAULT_PARSER_CLASSES": (
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ),
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "ForumOS API",
    "DESCRIPTION": "quiet places for loud ideas — API платформы онлайн-сообществ",
    "VERSION": env("APP_VERSION"),
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api",
    "SORT_OPERATIONS": False,
    "ENUM_NAME_OVERRIDES": {
        "ReactionEnum": "apps.reactions.models.ReactionKind.choices",
        "NotificationKindEnum": "apps.notifications.models.NotificationKind.choices",
        "RankEnum": "apps.accounts.models.Rank.choices",
    },
}

# ── Пагинация и фильтры ─────────────────────────────────────────────
CURSOR_PAGINATION_MAX_LIMIT = 100
FILTERS_MAX_LIMIT = 200

# ── Channels / WebSocket (TECHSPEC §12) ─────────────────────────────
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [env("CHANNELS_REDIS_URL",
                           default=REDIS_URL.replace("/0", "/1"))],
            "capacity": 1500,
            "expiry": 30,
        },
    },
}

# ── Celery (TECHSPEC §6.2) ──────────────────────────────────────────
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL.replace("/0", "/2"))
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL.replace("/0", "/4"))
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "UTC"
CELERY_ENABLE_UTC = True
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 4
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ROUTES = {
    "notifications.*": {"queue": "notifications"},
    "search.*": {"queue": "search"},
    "analytics.*": {"queue": "analytics"},
}
CELERY_BEAT_SCHEDULE = {
    "recompute-ranks": {
        "task": "events.tasks.refresh_ranks",
        "schedule": 300.0,
    },
    "cleanup-sessions": {
        "task": "events.tasks.cleanup_expired_tokens",
        "schedule": 3600.0,
    },
    "flush-event-outbox": {
        "task": "events.tasks.flush_outbox",
        "schedule": 60.0,
    },
}

# ── Кэш ─────────────────────────────────────────────────────────────
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "forumos",
    }
}

# ── Локализация и время ─────────────────────────────────────────────
# Всё хранится и отдаётся в UTC: смещения в API создают путаницу у клиентов.
LANGUAGE_CODE = "ru-ru"
TIME_ZONE = env("TIME_ZONE", default="UTC")
USE_I18N = True
USE_TZ = True

# ── Хранилище файлов ────────────────────────────────────────────────
USE_S3_STORAGE = env.bool("USE_S3_STORAGE", default=False)
AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID", default="forumos")
AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY", default="")
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="forumos-media")
AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", default="http://localhost:9000")
AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default="us-east-1")
AWS_QUERYSTRING_AUTH = False
AWS_DEFAULT_ACL = None
AWS_S3_FILE_OVERWRITE = False

if USE_S3_STORAGE:
    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3.S3Storage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
    }
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
    }

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
WHITENOISE_MAX_AGE = 60 * 60 * 24 * 30

AVATAR_MAX_BYTES = 2 * 1024 * 1024
ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024
AVATAR_ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp"]
ATTACHMENT_ALLOWED_TYPES = [*AVATAR_ALLOWED_TYPES, "application/pdf"]
BODY_MAX_LENGTH = 50_000
BIO_MAX_LENGTH = 500

# ── Kafka (TECHSPEC §13) ────────────────────────────────────────────
KAFKA_ENABLED = env.bool("KAFKA_ENABLED", default=False)
KAFKA_BOOTSTRAP_SERVERS = env("KAFKA_BOOTSTRAP_SERVERS", default="localhost:9092")
KAFKA_CONSUMER_GROUP_PREFIX = env("KAFKA_CONSUMER_GROUP_PREFIX", default="forumos")
KAFKA_CLIENT_ID = env("KAFKA_CLIENT_ID", default="forumos-backend")
KAFKA_CONSUMER_GROUP = env(
    "KAFKA_CONSUMER_GROUP", default=f"{KAFKA_CONSUMER_GROUP_PREFIX}-handlers")
KAFKA_TOPIC_POSTS = env("KAFKA_TOPIC_POSTS", default="forumos.posts.v1")
KAFKA_TOPIC_THREADS = env("KAFKA_TOPIC_THREADS", default="forumos.threads.v1")
KAFKA_TOPIC_USERS = env("KAFKA_TOPIC_USERS", default="forumos.users.v1")
KAFKA_TOPIC_NOTIFICATIONS = env("KAFKA_TOPIC_NOTIFICATIONS",
                                default="forumos.notifications.v1")
KAFKA_TOPIC_MODERATION = env("KAFKA_TOPIC_MODERATION", default="forumos.moderation.v1")
KAFKA_TOPIC_ANALYTICS = env("KAFKA_TOPIC_ANALYTICS", default="forumos.analytics.v1")
KAFKA_DLQ_SUFFIX = env("KAFKA_DLQ_SUFFIX", default=".dlq")
KAFKA_TOPIC_DLQ = f"{KAFKA_CONSUMER_GROUP_PREFIX}.dlq{KAFKA_DLQ_SUFFIX}"
KAFKA_MAX_RETRIES = env.int("KAFKA_MAX_RETRIES", default=3)
KAFKA_EVENT_MAX_AGE_DAYS = env.int("KAFKA_EVENT_MAX_AGE_DAYS", default=7)
KAFKA_OUTBOX_MODEL = "events.OutboxEvent"

# ── Elasticsearch (TECHSPEC §4.7) ───────────────────────────────────
ELASTIC_URL = env("ELASTIC_URL", default="http://localhost:9200")
ELASTIC_ENABLED = env.bool("ELASTIC_ENABLED", default=True)
ELASTIC_USERNAME = env("ELASTIC_USERNAME", default="")
ELASTIC_PASSWORD = env("ELASTIC_PASSWORD", default="")
ELASTIC_INDEX_PREFIX = env("ELASTIC_INDEX_PREFIX", default="forumos")
ELASTIC_TIMEOUT = env.int("ELASTIC_TIMEOUT", default=5)

# ── CORS / CSRF ─────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[env("APP_HOST")])
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    "accept", "authorization", "content-type", "origin", "user-agent",
    "x-csrftoken", "x-requested-with", "x-request-id",
]
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[env("APP_HOST")])
CSRF_COOKIE_NAME = "forumos_csrftoken"
CSRF_COOKIE_HTTPONLY = False
SESSION_COOKIE_NAME = "forumos_session"
CSRF_USE_SESSIONS = False

# Refresh-токен в httpOnly-cookie (TECHSPEC §15.1)
JWT_REFRESH_COOKIE_NAME = "forumos_refresh"
JWT_REFRESH_COOKIE_SECURE = env.bool("JWT_REFRESH_COOKIE_SECURE", default=not DEBUG)
JWT_REFRESH_COOKIE_SAMESITE = "Lax"
JWT_REFRESH_COOKIE_HTTPONLY = True

# ── Email (TECHSPEC §4.1) ───────────────────────────────────────────
EMAIL_BACKEND = env("EMAIL_BACKEND",
                    default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=25)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
DEFAULT_FROM_EMAIL = env("EMAIL_FROM", default="no-reply@forumos.local")

# ── Токены подтверждения (TECHSPEC §4.1) ────────────────────────────
EMAIL_VERIFICATION_TTL_HOURS = env.int("EMAIL_VERIFICATION_TTL_HOURS", default=24)
PASSWORD_RESET_TTL_HOURS = env.int("PASSWORD_RESET_TTL_HOURS", default=1)
EMAIL_VERIFICATION_RESEND_LIMIT = env.int("EMAIL_VERIFICATION_RESEND_LIMIT", default=3)

# ── Домен и версия ──────────────────────────────────────────────────
SITE_ID = 1
APP_NAME = "ForumOS"
APP_SLOGAN = "quiet places for loud ideas"
APP_VERSION = env("APP_VERSION")
APP_HOST = env("APP_HOST")
SITE_NAME = env("SITE_NAME", default=APP_NAME)
SITE_HOST = env("SITE_HOST", default=APP_HOST)
OG_FONT_PATHS = env.list("OG_FONT_PATHS", default=[
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
])

# ── Логирование (TECHSPEC §5.8) ─────────────────────────────────────
LOG_LEVEL = env("LOG_LEVEL")

# Django не резолвит строковые пути в аргументах форматтера, поэтому
# processors передаются как готовые callable-объекты.
_STRUCTLOG_PRE_CHAIN = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": structlog.processors.JSONRenderer(),
            "foreign_pre_chain": _STRUCTLOG_PRE_CHAIN,
        },
        "plain": {"format": "%(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "django.db.backends": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "forumos": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}

# ── Sentry (TECHSPEC §5.8) ──────────────────────────────────────────
SENTRY_DSN = env("SENTRY_DSN")
if SENTRY_DSN:  # pragma: no cover
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.redis import RedisIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=env("SENTRY_ENVIRONMENT", default="dev"),
        release=f"forumos@{APP_VERSION}",
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            RedisIntegration(),
            LoggingIntegration(level=logging.ERROR, event_level=logging.ERROR),
        ],
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.05),
        send_default_pii=False,
    )

# ── Прочее ──────────────────────────────────────────────────────────
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
DATA_UPLOAD_MAX_MEMORY_SIZE = ATTACHMENT_MAX_BYTES + 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FILES = 10
