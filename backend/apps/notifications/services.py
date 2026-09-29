"""Сервисы уведомлений (TECHSPEC §4.9)."""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from shared.logging import get_logger

from .models import Notification

logger = get_logger("forumos.notifications")


def create_notification(*, user_id: int, kind: str, payload: dict) -> Notification | None:
    """Создать уведомление и отправить его в WebSocket-канал пользователя.

    Отправка в WS синхронная (TECHSPEC §6.3): клиент получает событие
    немедленно, а в БД запись остаётся для истории.
    """
    if not user_id:
        return None
    if user_id == payload.get("actor_id"):
        return None  # не уведомляем о собственных действиях

    notification = Notification.objects.create(user_id=user_id, kind=kind, payload=payload)

    from ws.serializers import notification_payload

    _send_to_user(user_id, {
        "type": "notification",
        "notification": notification_payload(notification),
    })
    _send_to_user(user_id, {"type": "unread_count", "count": unread_count(user_id)})

    logger.info("notification_created", notification_id=notification.pk,
                user_id=user_id, kind=kind)
    return notification


def _send_to_user(user_id: int, message: dict) -> None:
    """Отправить в группу ``user_{id}`` (TECHSPEC §12.7)."""
    try:
        channel_layer = get_channel_layer()
        if channel_layer is None:  # pragma: no cover
            return
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}", {"type": "ws.deliver", "message": message}
        )
    except Exception as exc:  # pragma: no cover - WS недоступен, БД уже записана
        logger.warning("notification_ws_failed", user_id=user_id, error=str(exc)[:200])


def unread_count(user_id: int) -> int:
    """Количество непрочитанных уведомлений (TECHSPEC §4.9)."""
    return Notification.objects.filter(user_id=user_id, is_read=False).count()


def mark_read(notification: Notification) -> Notification:
    notification.mark_read()
    _send_to_user(notification.user_id, {"type": "unread_count",
                                         "count": unread_count(notification.user_id)})
    return notification


def mark_all_read(user_id: int) -> int:
    """Отметить все прочитанными (TECHSPEC §11.8)."""
    from django.utils import timezone

    count = Notification.objects.filter(user_id=user_id, is_read=False).update(
        is_read=True, updated_at=timezone.now()
    )
    _send_to_user(user_id, {"type": "unread_count", "count": 0})
    return count
