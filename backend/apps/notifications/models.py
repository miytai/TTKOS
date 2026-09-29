"""Модель уведомлений (TECHSPEC §4.9, §10.2)."""

from django.conf import settings
from django.db import models

from shared.models import TimeStampedModel


class NotificationKind(models.TextChoices):
    """Типы уведомлений (TECHSPEC §4.9)."""

    REPLY = "reply", "Ответ"
    MENTION = "mention", "Упоминание"
    REACTION = "reaction", "Реакция"
    QUOTE = "quote", "Цитата"
    SYSTEM = "system", "Системное"


class NotificationQuerySet(models.QuerySet):
    def unread(self):
        return self.filter(is_read=False)

    def for_user(self, user):
        return self.filter(user=user)


class Notification(TimeStampedModel):
    """Уведомление пользователя (TECHSPEC §10.2)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(max_length=32, choices=NotificationKind.choices,
                            verbose_name="Тип")
    payload = models.JSONField(default=dict, verbose_name="Данные")
    is_read = models.BooleanField(default=False, db_index=True, verbose_name="Прочитано")

    objects = NotificationQuerySet.as_manager()

    class Meta:
        verbose_name = "Уведомление"
        verbose_name_plural = "Уведомления"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="notif_user_created_idx"),
            models.Index(fields=["user", "is_read"], name="notif_user_unread_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} → {self.user_id}"

    # ── Производные значения ─────────────────────────────────────
    @property
    def actor(self):
        return self.payload.get("actor_username")

    @property
    def thread_slug(self):
        return self.payload.get("thread_slug")

    @property
    def post_id(self):
        return self.payload.get("post_id")

    def mark_read(self) -> None:
        if not self.is_read:
            self.is_read = True
            self.save(update_fields=["is_read", "updated_at"])
