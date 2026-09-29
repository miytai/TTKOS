ё"""SEO-модели (TECHSPEC §4.11)."""

from django.db import models

from shared.models import TimeStampedModel


class SEOMeta(TimeStampedModel):
    """Запись SEO-метаданных для пути (TECHSPEC §4.11)."""

    path = models.CharField(max_length=255, unique=True, verbose_name="Путь")
    title = models.CharField(max_length=255, blank=True, default="", verbose_name="Title")
    description = models.CharField(max_length=500, blank=True, default="",
                                   verbose_name="Description")
    keywords = models.CharField(max_length=500, blank=True, default="",
                                verbose_name="Ключевые слова")
    og_image = models.URLField(blank=True, default="", verbose_name="OG-изображение")
    canonical = models.CharField(max_length=255, blank=True, default="", verbose_name="Canonical")
    robots = models.CharField(max_length=100, blank=True, default="index, follow",
                              verbose_name="Robots")
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="Активна")
    priority = models.FloatField(default=0.7, verbose_name="Приоритет в sitemap")

    class Meta:
        verbose_name = "SEO-запись"
        verbose_name_plural = "SEO-записи"
        ordering = ["-priority", "path"]

    def __str__(self) -> str:
        return self.path

    @classmethod
    def for_path(cls, path: str) -> "SEOMeta | None":
        """Найти метаданные по пути (TECHSPEC §4.11)."""
        return cls.objects.filter(path=path, is_active=True).first()
