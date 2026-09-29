"""Модели тем и тегов (TECHSPEC §4.4, §10.2)."""

from django.conf import settings
from django.db import models
from django.urls import reverse

from shared.markdown import render_markdown
from shared.models import SoftDeleteModel, SoftDeleteQuerySet, TimeStampedModel
from shared.utils import extract_mentions, slugify


class Tag(TimeStampedModel):
    """Тег темы (TECHSPEC §4.4)."""

    name = models.CharField(max_length=40, verbose_name="Название")
    slug = models.SlugField(max_length=40, unique=True, verbose_name="URL")
    usage_count = models.IntegerField(default=0, db_index=True, verbose_name="Использований")

    class Meta:
        verbose_name = "Тег"
        verbose_name_plural = "Теги"
        ordering = ["-usage_count", "name"]
        indexes = [models.Index(fields=["-usage_count"], name="tag_usage_idx")]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = slugify(self.name, max_length=40)
        super().save(*args, **kwargs)


class ThreadQuerySet(SoftDeleteQuerySet):
    """Запросы лент тем (TECHSPEC §5.1: индексы + сортировки)."""

    def alive(self):
        return self.filter(is_deleted=False)

    def with_related(self):
        return self.select_related("forum", "author").prefetch_related("tags")

    def pinned_first(self):
        return self.order_by("-is_pinned", "-last_activity_at")


class Thread(SoftDeleteModel, TimeStampedModel):
    """Тема форума (TECHSPEC §10.2)."""

    MAX_PINNED_PER_FORUM = 3

    forum = models.ForeignKey(
        "forums.Forum", on_delete=models.PROTECT, related_name="threads",
        verbose_name="Раздел",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="threads", verbose_name="Автор",
    )
    title = models.CharField(max_length=200, verbose_name="Заголовок")
    slug = models.SlugField(max_length=220, unique=True, verbose_name="URL")
    body = models.TextField(verbose_name="Тело (markdown)")
    body_html = models.TextField(blank=True, default="", verbose_name="Тело (HTML)")
    tags = models.ManyToManyField(Tag, blank=True, related_name="threads", verbose_name="Теги")

    is_pinned = models.BooleanField(default=False, db_index=True, verbose_name="Закреплена")
    is_locked = models.BooleanField(default=False, verbose_name="Закрыта")
    is_draft = models.BooleanField(default=False, db_index=True, verbose_name="Черновик")

    views_count = models.PositiveIntegerField(default=0, verbose_name="Просмотры")
    posts_count = models.PositiveIntegerField(default=0, verbose_name="Постов")
    reactions_count = models.PositiveIntegerField(default=0, verbose_name="Реакций")

    last_activity_at = models.DateTimeField(db_index=True, verbose_name="Активность")

    objects = ThreadQuerySet.as_manager()
    all_objects = models.Manager()

    subscribers = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="subscribed_threads",
        through="threads.ThreadSubscription", verbose_name="Подписчики",
    )

    class Meta:
        verbose_name = "Тема"
        verbose_name_plural = "Темы"
        ordering = ["-is_pinned", "-last_activity_at"]
        indexes = [
            models.Index(fields=["forum", "-last_activity_at"], name="thread_forum_activity_idx"),
            models.Index(fields=["-created_at"], name="thread_created_idx"),
            models.Index(fields=["-reactions_count"], name="thread_reactions_idx"),
            models.Index(fields=["is_pinned", "-last_activity_at"], name="thread_pinned_idx"),
            models.Index(fields=["author", "-created_at"], name="thread_author_idx"),
        ]

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return reverse("thread-detail", kwargs={"slug": self.slug})

    def save(self, *args, **kwargs) -> None:
        from django.utils import timezone

        if not self.body_html:
            self.body_html = render_markdown(self.body)
        if not self.slug:
            self.slug = self._build_slug()
        if self._state.adding and not self.last_activity_at:
            self.last_activity_at = timezone.now()
        super().save(*args, **kwargs)

    def _build_slug(self) -> str:
        """Slug из заголовка + короткий суффикс для уникальности (TECHSPEC §11.5)."""
        import secrets

        base = slugify(self.title, max_length=210)
        candidate = f"{base}-{secrets.token_hex(3)}"
        if not Thread.all_objects.filter(slug=candidate).exists():
            return candidate
        return f"{base}-{secrets.token_hex(4)}"

    # ── Производные значения ─────────────────────────────────────
    @property
    def is_anonymous(self) -> bool:
        return self.author_id is None

    @property
    def author_display(self) -> str:
        return self.author.username if self.author_id else "удалённый аккаунт"

    @property
    def reading_time(self) -> int:
        """Оценка времени чтения, минут (TECHSPEC §1.2 — плотная информация)."""
        words = len(self.body.split())
        return max(1, round(words / 180))

    def mentions(self) -> list[str]:
        return extract_mentions(self.body)

    def subscribers_list(self):
        return self.subscribers.filter(is_active=True, is_deleted=False)

    # ── Бизнес-операции ──────────────────────────────────────────
    def increment_views(self) -> None:
        """Инкремент без гонок (F-выражение, TECHSPEC §5.1)."""
        Thread.all_objects.filter(pk=self.pk).update(
            views_count=models.F("views_count") + 1
        )
        self.views_count += 1

    def touch_activity(self) -> None:
        """Обновить время последней активности."""
        from django.utils import timezone

        now = timezone.now()
        self.last_activity_at = now
        Thread.all_objects.filter(pk=self.pk).update(last_activity_at=now)

    def can_edit(self, user) -> bool:
        """Правила редактирования (TECHSPEC §4.4)."""
        from datetime import timedelta

        from django.utils import timezone

        if not user or not user.is_authenticated:
            return False
        if user.is_superuser or user.is_staff:
            return True
        if self.forum.can_moderate(user):
            return True
        if self.author_id != user.pk:
            return False
        if user.rank.value in ("veteran", "legend", "moderator"):
            return True  # Veteran+ редактируют без лимита 24 часов
        return timezone.now() - self.created_at <= timedelta(hours=24)

    def can_moderate(self, user) -> bool:
        return self.forum.can_moderate(user)


class ThreadSubscription(TimeStampedModel):
    """Подписка на тему (TECHSPEC §4.4)."""

    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name="subscriptions")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="thread_subscriptions"
    )

    class Meta:
        verbose_name = "Подписка на тему"
        verbose_name_plural = "Подписки на темы"
        constraints = [
            models.UniqueConstraint(fields=["thread", "user"], name="unique_thread_subscription")
        ]
        indexes = [models.Index(fields=["user", "-created_at"], name="sub_user_created_idx")]

    def __str__(self) -> str:
        return f"{self.user.username} → {self.thread_id}"


class ThreadEdit(TimeStampedModel):
    """История редактирования темы — первые 5 версий (TECHSPEC §4.4)."""

    MAX_VERSIONS = 5

    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name="edits")
    editor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="thread_edits"
    )
    title = models.CharField(max_length=200, blank=True, default="")
    body = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Версия темы"
        verbose_name_plural = "Версии тем"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.thread_id} v{self.pk}"


class ThreadDraft(models.Model):
    """Автосохранение черновика раз в 10 секунд (TECHSPEC §4.4)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="thread_drafts"
    )
    forum = models.ForeignKey("forums.Forum", on_delete=models.CASCADE, null=True, blank=True)
    title = models.CharField(max_length=200, blank=True, default="")
    body = models.TextField(blank=True, default="")
    tags = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Черновик темы"
        verbose_name_plural = "Черновики тем"
        constraints = [
            models.UniqueConstraint(fields=["user"], name="unique_user_thread_draft")
        ]

    def __str__(self) -> str:
        return f"Черновик {self.user_id}"
