"""Модели модерации (TECHSPEC §4.10, §10.2)."""

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from shared.models import TimeStampedModel


class TargetType(models.TextChoices):
    """Что можно пометить жалобой (TECHSPEC §4.10)."""

    POST = "post", "Пост"
    THREAD = "thread", "Тема"
    USER = "user", "Пользователь"


class FlagReason(models.TextChoices):
    """Причины жалоб (TECHSPEC §4.10)."""

    SPAM = "spam", "Спам"
    ABUSE = "abuse", "Оскорбление"
    OFFTOPIC = "offtopic", "Офтоп"
    BOT = "bot", "Бот"
    OTHER = "other", "Другое"


class FlagStatus(models.TextChoices):
    """Статусы жалобы (TECHSPEC §4.10)."""

    OPEN = "open", "Открыта"
    RESOLVED = "resolved", "Решена"
    REJECTED = "rejected", "Отклонена"


class FlagQuerySet(models.QuerySet):
    def open(self):
        return self.filter(status=FlagStatus.OPEN)

    def pending(self):
        return self.filter(status=FlagStatus.OPEN).order_by("-created_at")


class Flag(TimeStampedModel):
    """Жалоба на контент или пользователя (TECHSPEC §4.10)."""

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="flags"
    )
    target_type = models.CharField(max_length=16, choices=TargetType.choices,
                                   verbose_name="Тип цели")
    target_id = models.BigIntegerField(verbose_name="ID цели")
    reason = models.CharField(max_length=32, choices=FlagReason.choices, verbose_name="Причина")
    comment = models.TextField(max_length=1000, blank=True, default="", verbose_name="Комментарий")
    status = models.CharField(max_length=16, choices=FlagStatus.choices,
                              default=FlagStatus.OPEN, db_index=True, verbose_name="Статус")
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="resolved_flags", verbose_name="Решил модератор",
    )
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name="Решено в")
    moderator_comment = models.TextField(max_length=1000, blank=True, default="")

    objects = FlagQuerySet.as_manager()

    class Meta:
        verbose_name = "Жалоба"
        verbose_name_plural = "Жалобы"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="flag_status_created_idx"),
            models.Index(fields=["target_type", "target_id"], name="flag_target_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["reporter", "target_type", "target_id"],
                name="unique_reporter_target",
            )
        ]

    def __str__(self) -> str:
        return f"{self.reason}:{self.target_type}#{self.target_id}"

    @property
    def target(self):
        """Объект жалобы; None, если удалён."""
        mapping = {
            TargetType.POST: ("apps.posts.models", "Post"),
            TargetType.THREAD: ("apps.threads.models", "Thread"),
            TargetType.USER: (settings.AUTH_USER_MODEL, "User"),
        }
        entry = mapping.get(self.target_type)
        if entry is None:
            return None
        module_path, class_name = entry
        from django.apps import apps as django_apps

        try:
            model = django_apps.get_model(module_path, class_name)
        except LookupError:  # pragma: no cover
            return None
        return model.objects.filter(pk=self.target_id).first()

    def resolve(self, moderator, comment: str = "") -> None:
        self.status = FlagStatus.RESOLVED
        self.resolved_by = moderator
        self.resolved_at = timezone.now()
        self.moderator_comment = comment[:1000]
        self.save(update_fields=["status", "resolved_by", "resolved_at",
                                 "moderator_comment", "updated_at"])

    def reject(self, moderator, comment: str = "") -> None:
        self.status = FlagStatus.REJECTED
        self.resolved_by = moderator
        self.resolved_at = timezone.now()
        self.moderator_comment = comment[:1000]
        self.save(update_fields=["status", "resolved_by", "resolved_at",
                                 "moderator_comment", "updated_at"])


class BanQuerySet(models.QuerySet):
    """Активные баны (TECHSPEC §4.10)."""

    def active(self) -> "BanQuerySet":
        now = timezone.now()
        return self.filter(is_active=True).filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)
        )

    def expired(self) -> "BanQuerySet":
        return self.filter(expires_at__isnull=False, expires_at__lte=timezone.now())


class Ban(TimeStampedModel):
    """Бан пользователя с TTL (TECHSPEC §4.10)."""

    objects = BanQuerySet.as_manager()

    DURATION_CHOICES = [
        ("1h", "1 час"),
        ("1d", "1 день"),
        ("7d", "7 дней"),
        ("30d", "30 дней"),
        ("forever", "Навсегда"),
    ]
    DURATION_MAP = {
        "1h": timedelta(hours=1),
        "1d": timedelta(days=1),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
        "forever": None,
    }

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bans"
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="issued_bans",
    )
    reason = models.CharField(max_length=1000, blank=True, default="")
    duration = models.CharField(max_length=16, choices=DURATION_CHOICES, default="1d")
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="Истекает")
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="Активен")
    lifted_at = models.DateTimeField(null=True, blank=True, verbose_name="Снят в")
    lifted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="lifted_bans",
    )

    class Meta:
        verbose_name = "Бан"
        verbose_name_plural = "Баны"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "is_active"], name="ban_user_active_idx")]

    def __str__(self) -> str:
        return f"Ban {self.user_id} ({self.duration})"

    @classmethod
    def active_for(cls, user_id: int):
        """Действующий бан пользователя или ``None`` (TECHSPEC §4.10)."""
        if not user_id:
            return None
        return cls.objects.filter(user_id=user_id).active().first()

    @classmethod
    def is_banned(cls, user_id: int) -> bool:
        return cls.active_for(user_id) is not None

    @classmethod
    def create_ban(cls, *, user, moderator, duration: str = "1d", reason: str = "") -> "Ban":
        ttl = cls.DURATION_MAP.get(duration)
        expires_at = timezone.now() + ttl if ttl else None
        # Новый бан снимает предыдущий
        cls.objects.filter(user=user, is_active=True).update(
            is_active=False, lifted_at=timezone.now()
        )
        return cls.objects.create(
            user=user, issued_by=moderator, reason=reason[:1000],
            duration=duration, expires_at=expires_at,
        )

    @property
    def is_expired(self) -> bool:
        return bool(self.expires_at and timezone.now() >= self.expires_at)

    @property
    def is_effective(self) -> bool:
        return self.is_active and not self.is_expired

    def lift(self, moderator=None) -> None:
        self.is_active = False
        self.lifted_at = timezone.now()
        self.lifted_by = moderator
        self.save(update_fields=["is_active", "lifted_at", "lifted_by", "updated_at"])


class AuditLog(TimeStampedModel):
    """Журнал действий модераторов, хранение 1 год (TECHSPEC §4.10)."""

    class Action(models.TextChoices):
        HIDE_POST = "post.hide", "Скрыть пост"
        DELETE_POST = "post.delete", "Удалить пост"
        DELETE_THREAD = "thread.delete", "Удалить тему"
        LOCK_THREAD = "thread.lock", "Закрыть тему"
        UNLOCK_THREAD = "thread.unlock", "Открыть тему"
        PIN_THREAD = "thread.pin", "Закрепить тему"
        UNPIN_THREAD = "thread.unpin", "Открепить тему"
        MOVE_THREAD = "thread.move", "Перенести тему"
        BAN_USER = "user.ban", "Забанить"
        UNBAN_USER = "user.unban", "Разбанить"
        WARN_USER = "user.warn", "Предупредить"
        RESOLVE_FLAG = "flag.resolve", "Обработать жалобу"
        REJECT_FLAG = "flag.reject", "Отклонить жалобу"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="audit_logs"
    )
    action = models.CharField(max_length=64, choices=Action.choices, verbose_name="Действие")
    target_type = models.CharField(max_length=16, blank=True, default="", verbose_name="Тип цели")
    target_id = models.BigIntegerField(null=True, blank=True, verbose_name="ID цели")
    payload = models.JSONField(default=dict, blank=True, verbose_name="Данные")

    class Meta:
        verbose_name = "Запись аудита"
        verbose_name_plural = "Записи аудита"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["actor", "-created_at"], name="audit_actor_idx"),
            models.Index(fields=["action", "-created_at"], name="audit_action_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.action} by {self.actor_id}"

    RETENTION_DAYS = 365

    @classmethod
    def log(cls, *, actor, action: str, target_type: str = "", target_id: int | None = None,
            **payload) -> "AuditLog":
        """Записать действие модератора (TECHSPEC §4.10)."""
        from shared.logging import audit_log as log_event

        entry = cls.objects.create(
            actor=actor, action=action, target_type=target_type,
            target_id=target_id, payload=payload,
        )
        log_event("moderation_action", actor_id=actor.pk, action=action,
                  target_type=target_type, target_id=target_id, **payload)
        return entry

    @classmethod
    def purge_expired(cls) -> int:
        """Удалить записи старше года."""
        deadline = timezone.now() - timedelta(days=cls.RETENTION_DAYS)
        deleted, _ = cls.objects.filter(created_at__lt=deadline).delete()
        return deleted
