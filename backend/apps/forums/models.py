"""Модели разделов (TECHSPEC §4.3, §10.2)."""

from django.conf import settings
from django.db import models
from django.urls import reverse

from shared.models import TimeStampedModel


class ForumQuerySet(models.QuerySet):
    """Разделы с предзагруженными счётчиками и детьми (TECHSPEC §1.2)."""

    def with_counts(self):
        return self.annotate(
            threads_total=models.Count("threads", filter=models.Q(threads__is_deleted=False),
                                      distinct=True),
        )

    def roots(self):
        return self.filter(parent__isnull=True)

    def tree(self):
        """Корневые разделы с детьми и счётчиками."""
        return (
            self.roots()
            .with_counts()
            .prefetch_related(
                models.Prefetch(
                    "children",
                    queryset=Forum.objects.with_counts().order_by("order", "name"),
                )
            )
            .order_by("order", "name")
        )


class Forum(TimeStampedModel):
    """Раздел форума. Вложенность — один уровень (TECHSPEC §4.3)."""

    name = models.CharField(max_length=120, verbose_name="Название")
    slug = models.SlugField(max_length=140, unique=True, verbose_name="URL")
    description = models.TextField(max_length=500, blank=True, default="", verbose_name="Описание")
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True,
        related_name="children", verbose_name="Родительский раздел",
    )
    accent = models.CharField(max_length=9, default="#7dd3a0", verbose_name="Акцентный цвет")
    icon = models.CharField(max_length=8, blank=True, default="", verbose_name="Иконка")
    order = models.IntegerField(default=0, db_index=True, verbose_name="Порядок")
    moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="moderated_forums", verbose_name="Модератор раздела",
    )
    is_closed = models.BooleanField(default=False, verbose_name="Закрыт для новых тем")

    objects = ForumQuerySet.as_manager()

    class Meta:
        verbose_name = "Раздел"
        verbose_name_plural = "Разделы"
        ordering = ["order", "name"]
        indexes = [models.Index(fields=["parent", "order"], name="forum_parent_order_idx")]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("forum-detail", kwargs={"slug": self.slug})

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            from shared.utils import unique_slug

            self.slug = unique_slug(self, self.name, max_length=140)
        super().save(*args, **kwargs)

    # ── Производные значения ─────────────────────────────────────
    @property
    def is_root(self) -> bool:
        return self.parent_id is None

    @property
    def level(self) -> int:
        return 1 if self.is_root else 2

    @property
    def thread_count(self) -> int:
        cached = getattr(self, "threads_total", None)
        if cached is not None:
            return cached
        return self.threads.filter(is_deleted=False).count()

    @property
    def post_count(self) -> int:
        from django.db.models import Sum


        aggregate = self.threads.filter(is_deleted=False).aggregate(total=Sum("posts_count"))
        return aggregate["total"] or 0

    @property
    def last_activity(self):
        return self.threads.filter(is_deleted=False).order_by("-last_activity_at").first()

    def can_moderate(self, user) -> bool:
        """Права модерации раздела (TECHSPEC §4.10)."""
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser or user.is_staff:
            return True
        if self.moderator_id == user.pk:
            return True
        # Модератор родительского раздела управляет и подразделами
        return bool(self.parent and self.parent.moderator_id == user.pk)
