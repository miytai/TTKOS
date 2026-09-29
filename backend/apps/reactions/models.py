"""Модели реакций (TECHSPEC §4.5, §10.2)."""

from django.conf import settings
from django.db import models

from shared.models import TimeStampedModel


class ReactionKind(models.TextChoices):
    """Пять типов реакций из ТЗ."""

    LIKE = "like", "👍 Нравится"
    FIRE = "fire", "🔥 Огонь"
    LAUGH = "laugh", "😂 Смешно"
    SAD = "sad", "😢 Грустно"
    WOW = "wow", "😮 Вау"


class Reaction(TimeStampedModel):
    """Тип реакции — заполняется сидом (TECHSPEC §10.2)."""

    code = models.CharField(max_length=16, unique=True, choices=ReactionKind.choices,
                            verbose_name="Код")
    emoji = models.CharField(max_length=8, verbose_name="Эмодзи")
    karma_value = models.IntegerField(default=1, verbose_name="Вес репутации")
    order = models.IntegerField(default=0, verbose_name="Порядок")

    class Meta:
        verbose_name = "Реакция"
        verbose_name_plural = "Реакции"
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.emoji} {self.code}"


class PostReaction(models.Model):
    """Реакция пользователя на пост (TECHSPEC §10.2)."""

    post = models.ForeignKey("posts.Post", on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="post_reactions"
    )
    reaction = models.ForeignKey(Reaction, on_delete=models.CASCADE, related_name="post_reactions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Реакция на пост"
        verbose_name_plural = "Реакции на посты"
        constraints = [
            models.UniqueConstraint(fields=["post", "user", "reaction"],
                                    name="unique_post_user_reaction")
        ]
        indexes = [
            models.Index(fields=["post", "reaction"], name="reaction_post_type_idx"),
            models.Index(fields=["user", "-created_at"], name="reaction_user_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.reaction_id} → {self.post_id}"

    @property
    def karma_delta(self) -> int:
        return self.reaction.karma_value
