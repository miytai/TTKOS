"""Celery-приложение ForumOS (TECHSPEC §6.2).

Импорт должен происходить до создания экземпляра приложения —
см. config/__init__.py.
"""

import os

from celery import Celery
from celery.signals import setup_logging

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("forumos")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@setup_logging.connect
def _configure_logging(**_kwargs) -> None:
    """Использовать structlog-конфигурацию из settings (TECHSPEC §5.8)."""
    from logging.config import dictConfig

    from django.conf import settings

    dictConfig(settings.LOGGING)


@app.task(bind=True, ignore_result=True)
def debug_task(self) -> str:  # pragma: no cover - диагностика
    return f"Задача {self.request.task} выполнена"
