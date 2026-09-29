"""Модели событийной шины: outbox для недоступного Kafka (TECHSPEC §13.2)."""

from django.db import models
from django.utils import timezone


class OutboxEvent(models.Model):
    """Событие, ожидающее доставки в Kafka.

    Используется, когда брокер недоступен: событие пишется в БД, а Celery
    повторяет отправку. Гарантирует, что событие не потеряется.
    """

    event_name = models.CharField(max_length=100, db_index=True, verbose_name="Событие")
    topic = models.CharField(max_length=100, db_index=True, verbose_name="Топик")
    payload = models.JSONField(default=dict, verbose_name="Данные")
    attempts = models.PositiveSmallIntegerField(default=0, verbose_name="Попытки")
    last_error = models.CharField(max_length=500, blank=True, default="",
                                  verbose_name="Последняя ошибка")
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name="Отправлено")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Создано")

    class Meta:
        verbose_name = "Событие outbox"
        verbose_name_plural = "События outbox"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["sent_at", "created_at"], name="outbox_pending_idx"),
        ]

    def __str__(self) -> str:
        state = "sent" if self.sent_at else "pending"
        return f"{self.event_name} ({state})"

    @property
    def is_pending(self) -> bool:
        return self.sent_at is None

    def mark_sent(self) -> None:
        self.sent_at = timezone.now()
        self.save(update_fields=["sent_at"])

    def mark_failed(self, error: str) -> None:
        self.attempts += 1
        self.last_error = error[:500]
        self.save(update_fields=["attempts", "last_error"])
