"""Настройки dev-окружения (TECHSPEC §17.2)."""

from .base import *  # noqa: F403
from .base import env

DEBUG = env.bool("DJANGO_DEBUG", default=True)

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["*"])

# Локальный Kafka включается, если переменная задана
KAFKA_ENABLED = env.bool("KAFKA_ENABLED", default=True)

EMAIL_BACKEND = env("EMAIL_BACKEND",
                    default="django.core.mail.backends.console.EmailBackend")

# В dev разрешаем любые хосты для django-debug-toolbar и MEDIA
MEDIA_URL = "/media/"

CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=["http://localhost:8080", "http://localhost:5173", "http://127.0.0.1:8080"],
)
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=["http://localhost:8080", "http://localhost:5173", "http://127.0.0.1:8080"],
)

# Упрощённые настройки для локальной разработки
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
JWT_REFRESH_COOKIE_SECURE = False
