"""WebSocket consumers (TECHSPEC §6.3)."""

from __future__ import annotations

import uuid

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from shared.logging import get_logger

from .presence import mark_offline, mark_online, online_users

logger = get_logger("forumos.ws")


class BaseConsumer(AsyncJsonWebsocketConsumer):
    """Общая логика аутентификации и групп (TECHSPEC §6.1)."""

    group_prefix = ""

    async def connect(self):
        user = self.scope.get("user")
        self.groups: list[str] = []

        if user is None or not user.is_authenticated:
            await self.close(code=4401)
            return

        if await self._is_banned(user.pk):
            await self.close(code=4403)
            return

        self.user = user
        if not await self.validate():
            return
        await self.accept()
        await self.on_connect()

    async def validate(self) -> bool:
        """Проверка прав/существования объекта до ``accept`` (TECHSPEC §6.3).

        Возвращает ``False``, если соединение нужно закрыть (наследник сам
        вызывает ``close`` с нужным кодом).
        """
        return True

    @staticmethod
    @database_sync_to_async
    def _is_banned(user_id: int) -> bool:
        from apps.moderation.models import Ban

        return Ban.is_banned(user_id)

    async def disconnect(self, code):
        await self.on_disconnect()
        for group in getattr(self, "groups", []):
            await self.channel_layer.group_discard(group, self.channel_name)

    async def on_connect(self) -> None:
        """Подключение к группам — переопределяется в наследниках."""

    async def on_disconnect(self) -> None:
        """Отключение — переопределяется в наследниках."""

    async def deliver(self, event) -> None:
        """Обработчик сообщений из channel layer (TECHSPEC §6.3)."""
        await self.send_json(event["message"])


class ThreadConsumer(BaseConsumer):
    """``/ws/threads/<slug>/`` — live-обновления темы (TECHSPEC §6.3)."""

    group_prefix = "thread"

    async def validate(self) -> bool:
        self.slug = self.scope["url_route"]["kwargs"]["slug"]
        self.thread = await self._get_thread(self.slug)
        if self.thread is None:
            await self.close(code=4404)
            return False
        return True

    async def on_connect(self) -> None:
        self.group = f"thread_{self.thread.pk}"
        self.groups = [self.group, f"user_{self.user.pk}"]
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.channel_layer.group_add(f"user_{self.user.pk}", self.channel_name)
        await database_sync_to_async(mark_online)(self.user.pk)

        await self.send_json({"type": "subscribed", "thread_id": self.thread.pk,
                              "slug": self.thread.slug})

    async def on_disconnect(self) -> None:
        if getattr(self, "thread", None) is not None:
            await database_sync_to_async(mark_offline)(self.user.pk, self.thread.pk)

    async def receive_json(self, content, **kwargs):
        """Клиент шлёт только heartbeat/ping (TECHSPEC §6.3)."""
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    @staticmethod
    @database_sync_to_async
    def _get_thread(slug: str):
        from apps.threads.models import Thread

        return Thread.objects.filter(slug=slug, is_deleted=False).first()

    # ── события группы (TECHSPEC §6.3) ──────────────────────────────
    async def post_created(self, event) -> None:
        await self.send_json({"type": "post.created", "post": event["post"]})

    async def post_updated(self, event) -> None:
        await self.send_json({"type": "post.updated", "post": event["post"]})

    async def post_deleted(self, event) -> None:
        await self.send_json({"type": "post.deleted", "post_id": event["post_id"]})

    async def reaction_toggled(self, event) -> None:
        await self.send_json({"type": "reaction", "reaction": event["reaction"]})

    async def thread_updated(self, event) -> None:
        await self.send_json({"type": "thread.updated", "thread": event["thread"]})


class NotificationConsumer(BaseConsumer):
    """``/ws/notifications/`` — уведомления текущего пользователя (TECHSPEC §6.3)."""

    async def on_connect(self) -> None:
        self.group = f"user_{self.user.pk}"
        self.groups = [self.group]
        await self.channel_layer.group_add(self.group, self.channel_name)

        from apps.notifications.services import unread_count

        count = await database_sync_to_async(unread_count)(self.user.pk)
        await self.send_json({"type": "unread_count", "count": count})

    async def receive_json(self, content, **kwargs):
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def notification(self, event) -> None:
        await self.send_json({"type": "notification", "notification": event["notification"]})

    async def unread_count(self, event) -> None:
        await self.send_json({"type": "unread_count", "count": event["count"]})


class OnlineConsumer(BaseConsumer):
    """``/ws/online/`` — кто онлайн в теме (TECHSPEC §6.3)."""

    async def on_connect(self) -> None:
        self.group = "online_global"
        self.groups = [self.group]
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.send_json({"type": "online_snapshot",
                              "users": await database_sync_to_async(online_users)()})

    async def receive_json(self, content, **kwargs):
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def presence_changed(self, event) -> None:
        await self.send_json({"type": "presence", **event["presence"]})


def new_connection_id() -> str:
    """Идентификатор соединения для presence (TECHSPEC §6.4)."""
    return uuid.uuid4().hex
