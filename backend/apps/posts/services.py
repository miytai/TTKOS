"""Сервисы постов: создание, редактирование, удаление (TECHSPEC §4.5)."""

from django.db import transaction
from django.db.models import F

from apps.accounts.models import UserProfile
from shared.logging import get_logger
from shared.utils import extract_mentions

from .models import Post, PostEdit

logger = get_logger("forumos.posts")


class ServiceError(Exception):
    """Доменная ошибка с кодом."""

    def __init__(self, message: str, code: str = "service_error", field: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.field = field


def list_thread_posts(thread, user):
    """Посты треда с учётом прав на удалённые (TECHSPEC §4.5)."""
    queryset = (
        Post.objects.filter(thread=thread)
        .with_related()
        .prefetch_related("attachments")
    )
    return queryset.visible_to(user).order_by("created_at", "id")


@transaction.atomic
def create_post(*, thread, author, body: str, parent_id: int | None = None,
                attachments: list | None = None) -> Post:
    """Создать пост, обновить счётчики темы и профиля, опубликовать событие."""
    if thread.is_locked:
        raise ServiceError("Тема закрыта для новых ответов", code="thread_locked")
    if thread.is_draft:
        raise ServiceError("Тема не опубликована", code="thread_draft")

    is_first = thread.posts_count == 0
    post = Post.objects.create(
        thread=thread,
        author=author,
        body=body,
        parent_id=parent_id,
        is_first_in_thread=is_first,
    )
    if attachments:
        for file in attachments:
            if not file:
                continue
            post.attachments.create(
                file=file,
                filename=getattr(file, "name", "file"),
                content_type=getattr(file, "content_type", "application/octet-stream"),
                size=getattr(file, "size", 0),
            )

    # Счётчик постов темы + время активности
    from apps.threads.models import Thread

    Thread.objects.filter(pk=thread.pk).update(posts_count=F("posts_count") + 1)
    thread.refresh_from_db()
    thread.touch_activity()

    if author_id := getattr(author, "pk", None):
        UserProfile.objects.filter(user_id=author_id).update(
            posts_count=F("posts_count") + 1
        )

    logger.info("post_created", post_id=post.pk, thread_id=thread.pk, author_id=author_id)

    from events.producer import publish_event

    publish_event("post.created", post_payload(post))
    _notify_subscribers(post)
    return post


def post_payload(post: Post) -> dict:
    """Полезная нагрузка события post.* (TECHSPEC §13.2)."""
    return {
        "id": post.pk,
        "thread_id": post.thread_id,
        "thread_slug": post.thread.slug,
        "forum_id": post.thread.forum_id,
        "forum_slug": post.thread.forum.slug,
        "author_id": post.author_id,
        "author_username": post.author_display,
        "parent_id": post.parent_id,
        "body_html": post.body_html[:2000],
        "created_at": post.created_at.isoformat(),
    }


def _notify_subscribers(post: Post) -> None:
    """Уведомления подписчикам и автору цитируемого поста (TECHSPEC §4.9)."""
    from django.contrib.auth import get_user_model

    from apps.notifications.services import create_notification

    UserModel = get_user_model()
    thread = post.thread
    payload_base = {
        "actor_id": post.author_id,
        "actor_username": post.author_display,
        "thread_id": thread.pk,
        "thread_slug": thread.slug,
        "thread_title": thread.title,
        "post_id": post.pk,
    }

    recipients: dict[int, tuple[str, str]] = {}

    if post.parent_id and post.parent.author_id:
        kind = "quote"
        recipients[post.parent.author_id] = (kind, dict(payload_base))

    if not post.is_first_in_thread and thread.author_id and thread.author_id != post.author_id:
        recipients.setdefault(thread.author_id, ("reply", dict(payload_base)))

    for user_id in thread.subscribers.exclude(pk=post.author_id).values_list("id", flat=True):
        recipients.setdefault(user_id, ("reply", dict(payload_base)))

    mentioned = UserModel.objects.filter(username__in=extract_mentions(post.body or ""))
    for user in mentioned:
        if user.pk == post.author_id:
            continue
        kind, payload = recipients.get(user.pk, ("mention", dict(payload_base)))
        recipients[user.pk] = ("mention", payload)

    for user_id, (kind, payload) in recipients.items():
        create_notification(user_id=user_id, kind=kind, payload=payload)


@transaction.atomic
def update_post(post: Post, user, *, body: str) -> Post:
    """Редактирование поста с проверкой прав (TECHSPEC §4.5)."""
    if not post.can_edit(user):
        raise ServiceError("Недостаточно прав для редактирования", code="forbidden")
    if post.is_deleted:
        raise ServiceError("Удалённый пост нельзя редактировать", code="post_deleted")

    PostEdit.objects.create(post=post, editor=user, body=post.body)
    # Храним только последние 5 версий
    excess = PostEdit.objects.filter(post=post).count() - 5
    if excess > 0:
        ids = PostEdit.objects.filter(post=post).order_by("created_at").values_list(
            "id", flat=True
        )[:excess]
        PostEdit.objects.filter(id__in=list(ids)).delete()

    from django.utils import timezone

    post.body = body
    post.body_html = ""  # пересчёт при save
    post.is_edited = True
    post.edited_at = timezone.now()
    post.save()

    from events.producer import publish_event

    publish_event("post.updated", post_payload(post))

    from ws.broadcast import broadcast_post_updated

    broadcast_post_updated(post.thread, post, actor_id=user.pk)
    logger.info("post_updated", post_id=post.pk, editor_id=user.pk)
    return post


@transaction.atomic
def soft_delete_post(post: Post, user, *, hard: bool = False) -> Post:
    """Мягкое удаление поста (TECHSPEC §4.5)."""
    if not post.can_delete(user):
        raise ServiceError("Недостаточно прав для удаления", code="forbidden")

    post.soft_delete()
    from apps.threads.models import Thread

    Thread.objects.filter(pk=post.thread_id).update(posts_count=F("posts_count") - 1)
    post.thread.refresh_from_db()
    post.thread.touch_activity()
    if post.author_id:
        UserProfile.objects.filter(user_id=post.author_id).update(
            posts_count=F("posts_count") - 1
        )
        # -1 репутация за удалённый пост (TECHSPEC §4.6)
        from apps.accounts.services import apply_reputation

        apply_reputation(post.author_id, -1, reason="post_deleted")

    from events.producer import publish_event

    publish_event("post.deleted", {"id": post.pk, "thread_id": post.thread_id,
                                    "thread_slug": post.thread.slug})

    from ws.broadcast import broadcast_post_deleted

    broadcast_post_deleted(post.thread, post.pk)
    logger.info("post_deleted", post_id=post.pk, actor_id=user.pk)
    return post
