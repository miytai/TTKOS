"""Сервисы тем: создание, модерация, счётчики (TECHSPEC §4.4)."""

from django.db import transaction
from django.db.models import F

from apps.accounts.models import UserProfile
from shared.logging import get_logger, security_log
from shared.utils import extract_mentions

from .models import Thread, ThreadEdit, ThreadSubscription

logger = get_logger("forumos.threads")


class ServiceError(Exception):
    """Доменная ошибка с кодом."""

    def __init__(self, message: str, code: str = "service_error", field: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.field = field


@transaction.atomic
def create_thread(*, author, forum, title: str, body: str, tags: list[str] | None = None,
                  is_draft: bool = False) -> Thread:
    """Создать тему, обновить счётчики профиля и опубликовать событие."""
    from .serializers import apply_tags

    thread = Thread.objects.create(
        author=author, forum=forum, title=title, body=body, is_draft=is_draft
    )
    if tags:
        apply_tags(thread, tags)

    UserProfile.objects.filter(user=author).update(threads_count=F("threads_count") + 1)
    logger.info("thread_created", thread_id=thread.pk, author_id=author.pk,
                forum_id=forum.pk, draft=is_draft)

    from events.producer import publish_event

    publish_event("thread.created", thread_payload(thread))
    return thread


def thread_payload(thread: Thread) -> dict:
    """Полезная нагрузка события thread.* (TECHSPEC §13.2)."""
    return {
        "id": thread.pk,
        "slug": thread.slug,
        "title": thread.title,
        "forum_id": thread.forum_id,
        "forum_slug": thread.forum.slug,
        "author_id": thread.author_id,
        "author_username": thread.author_display,
        "tags": list(thread.tags.values_list("slug", flat=True)),
        "posts_count": thread.posts_count,
        "reactions_count": thread.reactions_count,
        "created_at": thread.created_at.isoformat(),
        "last_activity_at": thread.last_activity_at.isoformat(),
    }


@transaction.atomic
def update_thread(thread: Thread, user, *, title: str | None = None,
                  body: str | None = None) -> Thread:
    """Обновить тему с проверкой прав и сохранением версии (TECHSPEC §4.4)."""
    if not thread.can_edit(user):
        raise ServiceError("Недостаточно прав для редактирования темы", code="forbidden")

    if body is not None and body != thread.body:
        save_edit_version(thread, user, title=title or thread.title, body=thread.body)

    if title is not None:
        thread.title = title
    if body is not None:
        thread.body = body
        thread.body_html = ""  # пересчёт при save
    thread.save()

    from events.producer import publish_event

    publish_event("thread.updated", thread_payload(thread))
    logger.info("thread_updated", thread_id=thread.pk, editor_id=user.pk)
    return thread


def save_edit_version(thread: Thread, editor, *, title: str, body: str) -> ThreadEdit:
    """Сохранить предыдущую версию — храним первые 5 (TECHSPEC §4.4)."""
    existing = thread.edits.count()
    edit = ThreadEdit.objects.create(thread=thread, editor=editor, title=title, body=body)
    if existing >= ThreadEdit.MAX_VERSIONS:
        oldest = thread.edits.order_by("created_at").first()
        if oldest:
            oldest.delete()
    return edit


@transaction.atomic
def soft_delete_thread(thread: Thread, user, *, hard: bool = False) -> Thread:
    """Удалить тему (soft-delete, TECHSPEC §4.4)."""
    moderator = thread.can_moderate(user)
    if thread.author_id != user.pk and not moderator:
        raise ServiceError("Недостаточно прав для удаления темы", code="forbidden")

    if hard and not moderator:
        raise ServiceError("Полное удаление доступно только модератору", code="forbidden")

    thread.soft_delete()
    if thread.author_id:
        UserProfile.objects.filter(user_id=thread.author_id).update(
            threads_count=F("threads_count") - 1
        )
    ThreadSubscription.objects.filter(thread=thread).delete()

    from events.producer import publish_event

    publish_event("thread.deleted", {"id": thread.pk, "slug": thread.slug,
                                     "forum_id": thread.forum_id})
    security_log("thread_deleted", thread_id=thread.pk, actor_id=user.pk, hard=hard)
    logger.info("thread_deleted", thread_id=thread.pk, actor_id=user.pk)
    return thread


@transaction.atomic
def set_pinned(thread: Thread, user, pinned: bool) -> Thread:
    """Закрепить тему — максимум 3 на раздел (TECHSPEC §4.4)."""
    if not thread.can_moderate(user):
        raise ServiceError("Закреплять темы может только модератор", code="forbidden")

    if pinned:
        current = Thread.objects.filter(forum_id=thread.forum_id, is_pinned=True,
                                        is_deleted=False).count()
        if current >= Thread.MAX_PINNED_PER_FORUM and not thread.is_pinned:
            raise ServiceError(
                f"В разделе уже {Thread.MAX_PINNED_PER_FORUM} закреплённых тем",
                code="pin_limit_reached",
            )

    thread.is_pinned = pinned
    thread.save(update_fields=["is_pinned", "updated_at"])
    logger.info("thread_pin_changed", thread_id=thread.pk, pinned=pinned, actor_id=user.pk)
    return thread


@transaction.atomic
def set_locked(thread: Thread, user, locked: bool) -> Thread:
    """Закрыть/открыть тему (TECHSPEC §4.4)."""
    if not thread.can_moderate(user):
        raise ServiceError("Закрывать темы может только модератор", code="forbidden")

    thread.is_locked = locked
    thread.save(update_fields=["is_locked", "updated_at"])
    security_log("thread_lock_changed", thread_id=thread.pk, locked=locked, actor_id=user.pk)
    return thread


@transaction.atomic
def move_thread(thread: Thread, user, target_forum) -> Thread:
    """Перенести тему в другой раздел (TECHSPEC §4.4)."""
    if not thread.can_moderate(user):
        raise ServiceError("Переносить темы может только модератор", code="forbidden")
    if thread.forum_id == target_forum.pk:
        raise ServiceError("Тема уже находится в этом разделе", code="same_forum")

    old_forum = thread.forum
    thread.forum = target_forum
    thread.save(update_fields=["forum", "updated_at"])
    security_log("thread_moved", thread_id=thread.pk, actor_id=user.pk,
                 from_forum=old_forum.pk, to_forum=target_forum.pk)
    return thread


# ── Подписки (TECHSPEC §4.4) ───────────────────────────────────────
def toggle_subscription(thread: Thread, user) -> dict:
    """Подписаться/отписаться от темы."""
    subscription = ThreadSubscription.objects.filter(thread=thread, user=user).first()
    if subscription:
        subscription.delete()
        return {"subscribed": False}
    ThreadSubscription.objects.get_or_create(thread=thread, user=user)
    return {"subscribed": True}


# ── Просмотры (TECHSPEC §4.4) ──────────────────────────────────────
def register_view(thread: Thread, user=None, request=None) -> None:
    """Зафиксировать просмотр темы и аналитическое событие."""
    thread.increment_views()

    from apps.analytics.models import EventLog

    EventLog.track(event_type=EventLog.Type.THREAD_VIEW, user=user, request=request,
                   thread_id=thread.pk, slug=thread.slug)


def notify_mentions(thread: Thread, *, author, request=None) -> list:
    """Создать уведомления об @упоминаниях в теле темы (TECHSPEC §4.9)."""
    from django.contrib.auth import get_user_model

    from apps.notifications.services import create_notification

    usernames = extract_mentions(thread.body or "")
    if not usernames:
        return []

    UserModel = get_user_model()
    mentioned = UserModel.objects.filter(username__in=usernames).exclude(pk=author.pk)
    created = []
    for user in mentioned:
        notification = create_notification(
            user=user,
            kind="mention",
            payload={
                "actor_id": author.pk,
                "actor_username": author.username,
                "thread_id": thread.pk,
                "thread_slug": thread.slug,
                "thread_title": thread.title,
                "context": "thread",
            },
        )
        if notification:
            created.append(notification)
    return created
