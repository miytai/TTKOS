"""Базовые абстрактные модели ForumOS (TECHSPEC §10.2)."""

import uuid

from django.db import models


class TimeStampedModel(models.Model):
    """Модель с автоматическими created_at / updated_at."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Создано")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    """QuerySet, скрывающий удалённые объекты по умолчанию."""

    def alive(self):
        return self.filter(is_deleted=False)

    def deleted(self):
        return self.filter(is_deleted=True)


class SoftDeleteModel(models.Model):
    """Мягкое удаление: объект скрыт, но доступен модератору (TECHSPEC §4.4)."""

    is_deleted = models.BooleanField(default=False, db_index=True, verbose_name="Удалён")
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="Удалён в")
    all_objects = models.Manager()

    objects = SoftDeleteQuerySet.as_manager()

    class Meta:
        abstract = True

    def soft_delete(self) -> None:
        from django.utils import timezone

        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])

    def restore(self) -> None:
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])


class UUIDMixin(models.Model):
    """Внешний идентификатор для объектов, публикуемых в ссылках."""

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    class Meta:
        abstract = True
