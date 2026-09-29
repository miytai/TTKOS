"""Точка входа пакета config — инициализация Celery."""

from .celery import app as celery_app

__all__ = ("celery_app",)
