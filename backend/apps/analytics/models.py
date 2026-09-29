"""Модель событий аналитики (TECHSPEC §10.2)."""

from django.conf import settings
from django.db import models

from shared.models import TimeStampedModel


class EventLog(TimeStampedModel):
    """Событие пользователя для аналитики и heatmap профиля (TECHSPEC §4.2)."""

    class Type(models.TextChoices):
        PAGE_VIEW = "page_view", "Просмотр страницы"
        THREAD_VIEW = "thread_view", "Просмотр темы"
        POST_CREATED = "post_created", "Создан пост"
        THREAD_CREATED = "thread_created", "Создана тема"
        REACTION_ADDED = "reaction_added", "Реакция"
        SEARCH = "search", "Поиск"
        LOGIN = "login", "Вход"
        REGISTER = "register", "Регистрация"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="events",
    )
    event_type = models.CharField(max_length=64, choices=Type.choices, db_index=True,
                                  verbose_name="Тип события")
    payload = models.JSONField(default=dict, blank=True, verbose_name="Данные")
    ip = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    user_agent = models.CharField(max_length=256, blank=True, default="")

    class Meta:
        verbose_name = "Событие"
        verbose_name_plural = "События"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["event_type", "-created_at"], name="event_type_created_idx"),
            models.Index(fields=["user", "-created_at"], name="event_user_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} by {self.user_id}"

    @classmethod
    def track(cls, *, event_type: str, user=None, request=None, **payload) -> "EventLog":
        """Записать событие с метаданными запроса."""
        from shared.logging import get_logger
        from shared.utils import client_ip

        ip = client_ip(request) if request is not None else None
        user_agent = ""
        if request is not None:
            user_agent = (request.META.get("HTTP_USER_AGENT") or "")[:256]

        event = cls.objects.create(
            user=user if (user and user.is_authenticated) else None,
            event_type=event_type,
            payload=payload,
            ip=ip or None,
            user_agent=user_agent,
        )
        get_logger("forumos.analytics").debug(
            "event_tracked", event_type=event_type, user_id=getattr(user, "pk", None)
        )
        return event
