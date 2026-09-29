"""Модели аккаунтов (TECHSPEC §10.2, §4.1, §4.2, §4.6)."""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from shared.models import TimeStampedModel
from shared.utils import USERNAME_RE


class Rank(models.TextChoices):
    """Ранги пользователей (TECHSPEC §4.6)."""

    NEWBIE = "newbie", "Newbie"
    MEMBER = "member", "Member"
    VETERAN = "veteran", "Veteran"
    LEGEND = "legend", "Legend"
    MODERATOR = "moderator", "Moderator"


#: Пороги рангов (TECHSPEC §4.6)
RANK_THRESHOLDS: list[tuple[int, Rank]] = [
    (5000, Rank.LEGEND),
    (500, Rank.VETERAN),
    (50, Rank.MEMBER),
    (0, Rank.NEWBIE),
]

#: Права рангов
RANK_CREATE_THREAD = {Rank.MEMBER, Rank.VETERAN, Rank.LEGEND, Rank.MODERATOR}
RANK_MODERATE_OWN_THREAD = {Rank.LEGEND, Rank.MODERATOR}


def rank_for_reputation(reputation: int) -> Rank:
    """Определить ранг по репутации (TECHSPEC §4.6)."""
    for threshold, rank in RANK_THRESHOLDS:
        if reputation >= threshold:
            return rank
    return Rank.NEWBIE


class Theme(models.TextChoices):
    """Тема оформления профиля (TECHSPEC §4.2)."""

    LIGHT = "light", "Light"
    DARK = "dark", "Dark"
    AUTO = "auto", "Auto"


class UserManager(DjangoUserManager):
    """Менеджер пользователей с email как USERNAME_FIELD."""

    def get_by_natural_key(self, username):
        return self.get(email__iexact=username)


class User(AbstractUser):
    """Пользователь ForumOS: вход по email, уникальный username."""

    email = models.EmailField(unique=True, db_index=True, verbose_name="Email")
    username = models.CharField(max_length=32, unique=True, verbose_name="Имя пользователя")
    is_email_verified = models.BooleanField(default=False, verbose_name="Email подтверждён")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Регистрация")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлён")
    is_deleted = models.BooleanField(default=False, db_index=True, verbose_name="Удалён")
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="Удалён в")

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    objects = UserManager()

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
        ordering = ["-date_joined"]
        indexes = [models.Index(fields=["-date_joined"], name="user_joined_idx")]

    def __str__(self) -> str:
        return self.username

    def clean(self) -> None:
        if self.username and not USERNAME_RE.match(self.username):
            raise ValidationError(
                {"username": "Username: 3–32 символа, латиница, цифры, подчёркивание"}
            )

    # ── Профиль ──────────────────────────────────────────────────
    @property
    def profile(self) -> "UserProfile":
        return self.userprofile

    @property
    def avatar_url(self) -> str | None:
        profile = getattr(self, "userprofile", None)
        if profile is None or not profile.avatar:
            return None
        try:
            return profile.avatar.url
        except ValueError:  # pragma: no cover - файл без пути
            return None

    @property
    def reputation(self) -> int:
        try:
            return self.userprofile.reputation
        except UserProfile.DoesNotExist:  # pragma: no cover
            return 0

    @property
    def can_create_thread(self) -> bool:
        if self.is_superuser or self.is_staff:
            return True
        if not self.is_email_verified:
            return False
        return self.rank in RANK_CREATE_THREAD

    @property
    def rank(self) -> Rank:
        return Rank(self.userprofile.rank)

    @property
    def is_anonymized(self) -> bool:
        return bool(self.is_deleted)

    @property
    def is_banned(self) -> bool:
        """Есть ли действующий бан (TECHSPEC §4.10)."""
        from apps.moderation.models import Ban

        return Ban.is_banned(self.pk)

    def anonymize(self) -> None:
        """Обезличивание аккаунта (TECHSPEC §4.2 «Удалить аккаунт»)."""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.email = f"deleted-{self.pk}-{int(timezone.now().timestamp())}@anonymized.invalid"
        self.username = f"deleted_{self.pk}"
        self.set_unusable_password()
        self.first_name = ""
        self.last_name = ""
        self.save(update_fields=[
            "is_deleted", "deleted_at", "email", "username",
            "password", "first_name", "last_name", "updated_at",
        ])

    def soft_delete(self) -> None:
        """Мягкое удаление с обезличиванием."""
        self.anonymize()


class UserProfile(TimeStampedModel):
    """Профиль пользователя (TECHSPEC §10.2)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="userprofile",
        verbose_name="Пользователь",
    )
    avatar = models.ImageField(upload_to="avatars/%Y/%m/", blank=True, verbose_name="Аватар")
    bio = models.TextField(max_length=500, blank=True, default="", verbose_name="О себе")
    location = models.CharField(max_length=64, blank=True, default="", verbose_name="Локация")
    website = models.URLField(max_length=200, blank=True, default="", verbose_name="Сайт")
    reputation = models.IntegerField(default=0, verbose_name="Репутация")
    rank = models.CharField(
        max_length=16, choices=Rank.choices, default=Rank.NEWBIE, verbose_name="Ранг"
    )
    last_seen_at = models.DateTimeField(null=True, blank=True, verbose_name="Был онлайн")

    # Настройки (TECHSPEC §4.2)
    theme = models.CharField(max_length=8, choices=Theme.choices, default=Theme.AUTO)
    show_online_status = models.BooleanField(default=True, verbose_name="Показывать онлайн-статус")
    notify_replies = models.BooleanField(default=True, verbose_name="Уведомлять об ответах")
    notify_mentions = models.BooleanField(default=True, verbose_name="Уведомлять об упоминаниях")
    notify_reactions = models.BooleanField(default=True, verbose_name="Уведомлять о реакциях")

    # Счётчики (TECHSPEC §4.2)
    threads_count = models.PositiveIntegerField(default=0, verbose_name="Тем создано")
    posts_count = models.PositiveIntegerField(default=0, verbose_name="Постов написано")
    reactions_received = models.PositiveIntegerField(default=0, verbose_name="Получено реакций")

    class Meta:
        verbose_name = "Профиль"
        verbose_name_plural = "Профили"
        indexes = [
            models.Index(fields=["rank"], name="profile_rank_idx"),
            models.Index(fields=["-reputation"], name="profile_reputation_idx"),
        ]

    def __str__(self) -> str:
        return f"Профиль {self.user.username}"

    # ── Производные значения ─────────────────────────────────────
    @property
    def rank_display(self) -> str:
        return dict(Rank.choices).get(self.rank, self.rank)

    @property
    def rank_progress(self) -> dict:
        """Прогресс до следующего ранга (для UI)."""
        thresholds = sorted({t for t, _ in RANK_THRESHOLDS})
        current = self.reputation
        next_threshold = next((t for t in thresholds if t > current), None)
        if next_threshold is None:
            return {"current_rank": self.rank, "next_rank": None, "progress": 100.0,
                    "remaining": 0}
        previous = max((t for t in thresholds if t <= current), default=0)
        span = next_threshold - previous
        progress = 0.0 if span <= 0 else (current - previous) / span * 100
        return {
            "current_rank": self.rank,
            "next_rank": rank_for_reputation(next_threshold).value,
            "progress": round(min(progress, 100.0), 2),
            "remaining": max(0, next_threshold - current),
        }

    @property
    def is_online(self) -> bool:
        """Онлайн по наличию активного WS-соединения (TECHSPEC §4.8)."""
        from ws.presence import is_user_online

        return is_user_online(self.user_id)

    def sync_rank(self, save: bool = True) -> Rank:
        """Пересчитать ранг по репутации."""
        new_rank = rank_for_reputation(self.reputation)
        if new_rank != self.rank:
            old_rank = self.rank
            self.rank = new_rank.value
            if save:
                self.save(update_fields=["rank", "updated_at"])
            from shared.logging import get_logger

            get_logger("forumos.accounts").info(
                "rank_changed", user_id=self.user_id,
                old_rank=old_rank, new_rank=self.rank,
            )
        return new_rank

    def add_reputation(self, delta: int, reason: str = "") -> None:
        """Изменить репутацию и пересчитать ранг (TECHSPEC §4.6)."""
        self.reputation = max(0, self.reputation + delta)
        self.sync_rank(save=False)
        self.save(update_fields=["reputation", "rank", "updated_at"])

        from shared.logging import get_logger

        get_logger("forumos.accounts").info(
            "reputation_changed", user_id=self.user_id,
            delta=delta, reason=reason, reputation=self.reputation,
        )


class VerificationToken(TimeStampedModel):
    """Токен подтверждения email или сброса пароля (TECHSPEC §4.1).

    Хранится только хэш токена: утечка БД не даёт возможности войти.
    """

    class Purpose(models.TextChoices):
        EMAIL_VERIFICATION = "email_verification", "Подтверждение email"
        PASSWORD_RESET = "password_reset", "Сброс пароля"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="verification_tokens"
    )
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    expires_at = models.DateTimeField(verbose_name="Истекает")
    used_at = models.DateTimeField(null=True, blank=True, verbose_name="Использован")

    class Meta:
        verbose_name = "Токен верификации"
        verbose_name_plural = "Токены верификации"
        indexes = [models.Index(fields=["user", "purpose"], name="token_user_purpose_idx")]

    def __str__(self) -> str:
        return f"{self.purpose}:{self.user_id}"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_usable(self) -> bool:
        return self.used_at is None and not self.is_expired

    def mark_used(self) -> None:
        self.used_at = timezone.now()
        self.save(update_fields=["used_at", "updated_at"])

    @classmethod
    def expiry_for(cls, purpose: str) -> timedelta:
        if purpose == cls.Purpose.PASSWORD_RESET:
            return timedelta(hours=settings.PASSWORD_RESET_TTL_HOURS)
        return timedelta(hours=settings.EMAIL_VERIFICATION_TTL_HOURS)


class Achievement(TimeStampedModel):
    """Описание ачивки (TECHSPEC §4.6)."""

    class Kind(models.TextChoices):
        THREADS = "threads", "Темы"
        POSTS = "posts", "Посты"
        REACTIONS = "reactions", "Реакции"
        REPUTATION = "reputation", "Репутация"
        SPECIAL = "special", "Особые"

    code = models.SlugField(max_length=40, unique=True)
    title = models.CharField(max_length=64)
    description = models.CharField(max_length=200, blank=True, default="")
    icon = models.CharField(max_length=8, blank=True, default="🏅")
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.SPECIAL)
    threshold = models.PositiveIntegerField(default=1)
    order = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Ачивка"
        verbose_name_plural = "Ачивки"
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.icon} {self.title}"

    def is_unlocked_for(self, profile: UserProfile) -> bool:
        """Проверить условие получения по текущим счётчикам профиля."""
        if self.kind == Achievement.Kind.THREADS:
            return profile.threads_count >= self.threshold
        if self.kind == Achievement.Kind.POSTS:
            return profile.posts_count >= self.threshold
        if self.kind == Achievement.Kind.REACTIONS:
            return profile.reactions_received >= self.threshold
        if self.kind == Achievement.Kind.REPUTATION:
            return profile.reputation >= self.threshold
        return False


class UserAchievement(models.Model):
    """Выданная ачивка пользователю."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="achievements"
    )
    achievement = models.ForeignKey(
        Achievement, on_delete=models.CASCADE, related_name="user_achievements"
    )
    unlocked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ачивка пользователя"
        verbose_name_plural = "Ачивки пользователей"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "achievement"], name="unique_user_achievement"
            )
        ]

    def __str__(self) -> str:
        return f"{self.user.username}: {self.achievement.code}"
