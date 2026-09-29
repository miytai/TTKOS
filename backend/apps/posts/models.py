"""Модели постов (TECHSPEC §4.5, §10.2)."""

from django.conf import settings
from django.db import models

from shared.markdown import render_markdown
from shared.models import SoftDeleteModel, SoftDeleteQuerySet, TimeStampedModel


class Attachment(models.Model):
    """Вложение поста — файл в MinIO/S3 (TECHSPEC §15.7)."""

    post = models.ForeignKey("posts.Post", on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="attachments/%Y/%m/", verbose_name="Файл")
    filename = models.CharField(max_length=255, verbose_name="Исходное имя")
    content_type = models.CharField(max_length=100, verbose_name="MIME")
    size = models.PositiveIntegerField(default=0, verbose_name="Размер, байт")

    class Meta:
        verbose_name = "Вложение"
        verbose_name_plural = "Вложения"
        ordering = ["id"]

    def __str__(self) -> str:
        return self.filename

    @property
    def url(self) -> str:
        return self.file.url

    @property
    def is_image(self) -> bool:
        return self.content_type.startswith("image/")

    @property
    def human_size(self) -> str:
        size = float(self.size)
        for unit in ("Б", "КБ", "МБ"):
            if size < 1024:
                return f"{size:.0f} {unit}" if unit == "Б" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} ГБ"


class PostQuerySet(SoftDeleteQuerySet):
    """Запросы постов треда."""

    def with_related(self):
        return self.select_related("author", "thread", "thread__forum")

    def visible_to(self, user):
        """Удалённые посты видны автору и модераторам (TECHSPEC §4.5)."""
        if user is not None and user.is_authenticated and (user.is_staff or user.is_superuser):
            return self
        if user is not None and user.is_authenticated:
            return self.filter(models.Q(is_deleted=False) | models.Q(author=user))
        return self.filter(is_deleted=False)


class Post(SoftDeleteModel, TimeStampedModel):
    """Сообщение в теме (TECHSPEC §10.2)."""

    thread = models.ForeignKey("threads.Thread", on_delete=models.CASCADE, related_name="posts",
                               verbose_name="Тема")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="posts", verbose_name="Автор",
    )
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="replies", verbose_name="Цитируемый пост",
    )
    body = models.TextField(verbose_name="Тело (markdown)")
    body_html = models.TextField(blank=True, default="", verbose_name="Тело (HTML)")

    is_edited = models.BooleanField(default=False, verbose_name="Редактирован")
    edited_at = models.DateTimeField(null=True, blank=True, verbose_name="Отредактирован")
    reactions_count = models.PositiveIntegerField(default=0, verbose_name="Реакций")
    is_first_in_thread = models.BooleanField(default=False, verbose_name="Первый пост темы")

    objects = PostQuerySet.as_manager()
    all_objects = models.Manager()

    class Meta:
        verbose_name = "Пост"
        verbose_name_plural = "Посты"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["thread", "created_at"], name="post_thread_created_idx"),
            models.Index(fields=["author", "-created_at"], name="post_author_idx"),
            models.Index(fields=["-reactions_count"], name="post_reactions_idx"),
        ]

    def __str__(self) -> str:
        return f"Пост #{self.pk} в теме {self.thread_id}"

    def save(self, *args, **kwargs) -> None:
        if not self.body_html:
            self.body_html = render_markdown(self.body)
        super().save(*args, **kwargs)

    # ── Производные значения ─────────────────────────────────────
    @property
    def author_display(self) -> str:
        return self.author.username if self.author_id else "удалённый аккаунт"

    @property
    def quote_depth(self) -> int:
        """Глубина вложенной цитаты — максимум 3 (TECHSPEC §4.5)."""
        depth, parent, seen = 0, self.parent, set()
        while parent is not None and parent.pk not in seen:
            seen.add(parent.pk)
            depth += 1
            parent = parent.parent
        return depth

    @property
    def reply_count(self) -> int:
        """Количество прямых ответов на пост (TECHSPEC §4.5)."""
        cached = getattr(self, "replies_total", None)
        if cached is not None:
            return cached
        return self.replies.filter(is_deleted=False).count()

    def can_edit(self, user) -> bool:
        """Правила редактирования поста (TECHSPEC §4.5)."""
        from datetime import timedelta

        from django.utils import timezone

        if not user or not user.is_authenticated:
            return False
        if user.is_superuser or user.is_staff:
            return True
        if self.thread.forum.can_moderate(user):
            return True
        if self.author_id != user.pk:
            return False
        if user.rank.value in ("veteran", "legend", "moderator"):
            return True
        return timezone.now() - self.created_at <= timedelta(hours=24)

    def can_delete(self, user) -> bool:
        """Удалять может автор или модератор раздела (TECHSPEC §4.5)."""
        if not user or not user.is_authenticated:
            return False
        if user.is_staff or user.is_superuser:
            return True
        return self.author_id == user.pk or self.thread.forum.can_moderate(user)

    def can_view(self, user) -> bool:
        """Удалённый пост виден автору и модераторам."""
        if not self.is_deleted:
            return True
        if not user or not user.is_authenticated:
            return False
        return bool(user.is_staff or user.is_superuser or self.author_id == user.pk
                    or self.thread.forum.can_moderate(user))


class PostEdit(TimeStampedModel):
    """История редактирования поста (TECHSPEC §4.5)."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="edits")
    editor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="post_edits"
    )
    body = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Версия поста"
        verbose_name_plural = "Версии постов"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Пост #{self.post_id} v{self.pk}"
