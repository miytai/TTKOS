"""Отправка событий в WebSocket-группы (TECHSPEC §6.3)."""

from __future__ import annotations

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from shared.logging import get_logger

logger = get_logger("forumos.ws.broadcast")


def _group_send(group: str, message_type: str, payload: dict) -> bool:
    """Отправить событие в группу; ошибки не пробрасываются в вызывающий код."""
    try:
        layer = get_channel_layer()
        if layer is None:  # pragma: no cover
            return False
        async_to_sync(layer.group_send)(group, {"type": message_type, **payload})
        return True
    except Exception as exc:  # pragma: no cover
        logger.warning("ws_broadcast_failed", group=group, event_name=message_type,
                       error=str(exc)[:200])
        return False


def _thread_id(thread) -> int:
    return thread.pk if hasattr(thread, "pk") else int(thread)


def broadcast_post_created(thread, post, actor_id: int | None = None) -> bool:
    """Новый пост в теме (TECHSPEC §6.3)."""
    from .serializers import post_payload

    return _group_send(f"thread_{_thread_id(thread)}", "post.created",
                       {"post": post_payload(post), "actor_id": actor_id})


def broadcast_post_updated(thread, post, actor_id: int | None = None) -> bool:
    """Редактирование поста (TECHSPEC §6.3)."""
    from .serializers import post_payload

    return _group_send(f"thread_{_thread_id(thread)}", "post.updated",
                       {"post": post_payload(post), "actor_id": actor_id})


def broadcast_post_deleted(thread, post_id: int) -> bool:
    """Удаление/скрытие поста (TECHSPEC §6.3)."""
    return _group_send(f"thread_{_thread_id(thread)}", "post.deleted",
                       {"post_id": post_id})


def broadcast_reaction(post, result: dict, actor_id: int | None = None) -> bool:
    """Toggle реакции (TECHSPEC §6.3)."""
    from .serializers import reaction_payload

    payload = reaction_payload(
        thread_id=post.thread_id,
        post_id=post.pk,
        target_type=result.get("target_type", "post"),
        target_id=result.get("target_id", post.pk),
        user_id=actor_id or 0,
        username=result.get("username", ""),
        emoji=result.get("code", ""),
        active=result.get("active", False),
        counts=result.get("counts", {}),
    )
    return _group_send(f"thread_{post.thread_id}", "reaction.toggled", {"reaction": payload})


def broadcast_thread_updated(thread) -> bool:
    """Изменение счётчиков темы (TECHSPEC §6.3)."""
    from .serializers import thread_payload

    return _group_send(f"thread_{thread.pk}", "thread.updated", {"thread": thread_payload(thread)})


def broadcast_online(*, user_id: int, username: str, online: bool) -> bool:
    """Изменение presence (TECHSPEC §6.4)."""
    return _group_send("online_global", "presence.changed",
                       {"presence": {"user_id": user_id, "username": username,
                                     "online": online}})
