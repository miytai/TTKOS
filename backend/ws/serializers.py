"""WS-сериализаторы для отправки событий в Channels (TECHSPEC §6.3)."""

from apps.notifications.models import Notification
from apps.posts.models import Post
from apps.threads.models import Thread


def notification_payload(notification: Notification) -> dict:
    """Уведомление в формате для WebSocket (TECHSPEC §4.9)."""
    return {
        "id": notification.pk,
        "kind": notification.kind,
        "is_read": notification.is_read,
        "created_at": notification.created_at.isoformat(),
        "actor_username": notification.actor,
        "thread_slug": notification.thread_slug,
        "post_id": notification.post_id,
        "message": (notification.payload or {}).get("message", ""),
    }


def post_payload(post: Post) -> dict:
    """Пост в формате для WebSocket (TECHSPEC §6.3)."""
    return {
        "id": post.pk,
        "thread_id": post.thread_id,
        "thread_slug": post.thread.slug,
        "body": post.body,
        "author": {
            "id": post.author_id,
            "username": post.author_display,
        },
        "created_at": post.created_at.isoformat(),
        "edited_at": post.edited_at.isoformat() if post.edited_at else None,
        "reply_count": post.reply_count,
    }


def thread_payload(thread: Thread) -> dict:
    """Тема в формате для WebSocket (TECHSPEC §6.3)."""
    return {
        "id": thread.pk,
        "slug": thread.slug,
        "title": thread.title,
        "posts_count": thread.posts_count,
        "last_activity_at": thread.last_activity_at.isoformat(),
        "author": {"id": thread.author_id, "username": thread.author_display},
    }


def reaction_payload(*, thread_id: int, post_id: int, target_type: str,
                     target_id: int, user_id: int, username: str,
                     emoji: str, active: bool, counts: dict) -> dict:
    """Реакция в формате для WebSocket (TECHSPEC §6.3)."""
    return {
        "thread_id": thread_id,
        "post_id": post_id,
        "target_type": target_type,
        "target_id": target_id,
        "user_id": user_id,
        "username": username,
        "emoji": emoji,
        "active": active,
        "counts": counts,
    }
