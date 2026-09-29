"""Настройки test-окружения (TECHSPEC §16.1)."""

from .base import *  # noqa: F403
from .base import env

DEBUG = False
SECRET_KEY = env("DJANGO_SECRET_KEY", default="test-secret-key-not-for-production")

ALLOWED_HOSTS = ["*", "testserver"]

# Синхронные задачи — без брокера (TECHSPEC §16.1)
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# In-memory кэш и каналы: тесты не должны зависеть от Redis
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "forumos-tests",
    }
}
CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}

# Хранилище во временном каталоге теста
import tempfile  # noqa: E402

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Kafka и Elasticsearch выключены — используются заглушки
KAFKA_ENABLED = False
ELASTIC_ENABLED = False

# Логи только в консоль, без внешних сервисов
LOGGING["root"]["level"] = "CRITICAL"  # noqa: F405
SENTRY_DSN = ""

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

JWT_REFRESH_COOKIE_SECURE = False
MEDIA_ROOT = tempfile.mkdtemp(prefix="forumos-test-media-")

TEST_RUNNER = "django.test.runner.DiscoverRunner"
