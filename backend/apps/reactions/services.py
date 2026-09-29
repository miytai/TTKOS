"""Сервисы реакций (TECHSPEC §4.5, §4.6)."""

from django.db import transaction
from django.db.models import Count, F

from shared.logging import get_logger

from .models import PostReaction, Reaction

logger = get_logger("forumos.reactions")


class ServiceError(Exception):
    """Доменная ошибка с кодом."""

    def __init__(self, message: str, code: str = "service_error", field: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.field = field


@transaction.atomic
def toggle_reaction(post, user, code: str) -> dict:
    """Добавить/убрать реакцию пользователя (TECHSPEC §4.5).

    Возвращает состояние и счётчики; события ``reaction.added`` /
    ``reaction.removed`` уходят в Kafka (TECHSPEC §13.1).
    """
    reaction = Reaction.objects.filter(code=code).first()
    if reaction is None:
        raise ServiceError("Неизвестный тип реакции", code="unknown_reaction", field="reaction")

    if post.author_id == user.pk:
        raise ServiceError("Нельзя реагировать на собственный пост",
                           code="own_post", field="post")

    existing = PostReaction.objects.filter(post=post, user=user, reaction=reaction).first()

    if existing:
        existing.delete()
        _update_counter(post, -1)
        event, state = "reaction.removed", "removed"
        delta = -reaction.karma_value
    else:
        PostReaction.objects.create(post=post, user=user, reaction=reaction)
        _update_counter(post, 1)
        event, state = "reaction.added", "added"
        delta = reaction.karma_value

    # Репутация автора поста (TECHSPEC §4.6)
    if post.author_id and delta:
        from apps.accounts.services import apply_reputation

        apply_reputation(post.author_id, delta, reason=f"reaction:{code}")
        if state == "added":
            from apps.accounts.models import UserProfile

            UserProfile.objects.filter(user_id=post.author_id).update(
                reactions_received=F("reactions_received") + 1
            )

    payload = {
        "post_id": post.pk,
        "thread_id": post.thread_id,
        "thread_slug": post.thread.slug,
        "user_id": user.pk,
        "username": user.username,
        "reaction": code,
        "emoji": reaction.emoji,
        "karma_delta": delta,
    }
    from events.producer import publish_event

    publish_event(event, payload)

    if state == "added" and post.author_id and post.author_id != user.pk:
        from apps.notifications.services import create_notification

        profile_notify = _notifications_enabled(post.author_id, "notify_reactions")
        if profile_notify:
            create_notification(
                user_id=post.author_id,
                kind="reaction",
                payload={
                    "actor_id": user.pk,
                    "actor_username": user.username,
                    "thread_id": post.thread_id,
                    "thread_slug": post.thread.slug,
                    "thread_title": post.thread.title,
                    "post_id": post.pk,
                    "reaction": code,
                    "emoji": reaction.emoji,
                },
            )

    # Ачивки «1000 лайков» и т.п. — через событие achievement.unlocked
    from apps.accounts.services import evaluate_achievements

    evaluate_achievements(post.author_id)

    logger.info("reaction_toggled", post_id=post.pk, user_id=user.pk,
                reaction=code, state=state)
    return {
        "post_id": post.pk,
        "reaction": code,
        "state": state,
        "active": state == "added",
        "emoji": reaction.emoji,
        "karma_value": reaction.karma_value,
        "reactions_count": post.reactions_count,
        "counts": reaction_counts(post),
        "mine": my_reactions(post, user),
    }


def _notifications_enabled(user_id: int, field: str) -> bool:
    from apps.accounts.models import UserProfile

    profile = UserProfile.objects.filter(user_id=user_id).only(field).first()
    return bool(getattr(profile, field, False)) if profile else True


def _update_counter(post, delta: int) -> None:
    from apps.posts.models import Post

    Post.objects.filter(pk=post.pk).update(reactions_count=F("reactions_count") + delta)
    post.refresh_from_db()


def reaction_counts(post) -> dict:
    """Счётчики реакций поста в виде ``{code: count}`` для всех типов справочника."""
    counts = {row["code"]: 0 for row in Reaction.objects.values("code")}
    rows = (
        PostReaction.objects.filter(post=post)
        .values("reaction__code")
        .annotate(count=Count("id"))
        .order_by()
    )
    counts.update({row["reaction__code"]: row["count"] for row in rows})
    return counts


def my_reactions(post, user) -> list[str]:
    if user is None or not user.is_authenticated:
        return []
    return list(
        PostReaction.objects.filter(post=post, user=user).values_list("reaction__code", flat=True)
    )


def seed_reactions() -> list[Reaction]:
    """Наполнить справочник реакций из ТЗ (TECHSPEC §4.5)."""
    data = [
        ("like", "👍", 1, 0),
        ("fire", "🔥", 1, 1),
        ("laugh", "😂", 1, 2),
        ("sad", "😢", 1, 3),
        ("wow", "😮", 1, 4),
    ]
    created = []
    for code, emoji, karma, order in data:
        reaction, _ = Reaction.objects.update_or_create(
            code=code, defaults={"emoji": emoji, "karma_value": karma, "order": order}
        )
        created.append(reaction)
    return created
