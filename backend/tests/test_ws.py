"""WebSocket: подключение, группы и доставка событий (TECHSPEC §6.3, §16)."""

import pytest
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator

from ws.routing import websocket_urlpatterns


async def _asgi_app(user):
    """Приложение WS с уже разрешённым пользователем (минуя JWT-middleware)."""

    class InjectUser:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            scope = dict(scope)
            scope["user"] = user
            return await self.app(scope, receive, send)

    return InjectUser(URLRouter(websocket_urlpatterns))


@pytest.mark.django_db(transaction=True)
async def test_anonymous_ws_closed(user, thread):
    from django.contrib.auth.models import AnonymousUser

    app = await _asgi_app(AnonymousUser())
    communicator = WebsocketCommunicator(app, f"/ws/threads/{thread.slug}/")

    connected, code = await communicator.connect()

    assert connected is False
    assert code == 4401
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_thread_subscription_and_ping(user, thread):
    app = await _asgi_app(user)
    communicator = WebsocketCommunicator(app, f"/ws/threads/{thread.slug}/")

    connected, _ = await communicator.connect()
    assert connected is True

    subscribed = await communicator.receive_json_from()
    assert subscribed["type"] == "subscribed"
    assert subscribed["thread_id"] == thread.pk

    await communicator.send_json_to({"type": "ping"})
    assert (await communicator.receive_json_from())["type"] == "pong"

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_thread_subscription_unknown_slug(user):
    app = await _asgi_app(user)
    communicator = WebsocketCommunicator(app, "/ws/threads/does-not-exist/")

    connected, code = await communicator.connect()

    assert connected is False
    assert code == 4404
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_banned_user_ws_closed(user, moderator):
    from channels.db import database_sync_to_async as dbs

    from apps.moderation.services import ban_user

    await dbs(ban_user)(target_user=user, moderator=moderator, duration="1d")
    app = await _asgi_app(user)
    communicator = WebsocketCommunicator(app, "/ws/notifications/")

    connected, code = await communicator.connect()

    assert connected is False
    assert code == 4403
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_broadcast_post_created_reaches_thread(user, thread, post):
    from channels.layers import get_channel_layer

    app = await _asgi_app(user)
    communicator = WebsocketCommunicator(app, f"/ws/threads/{thread.slug}/")
    connected, _ = await communicator.connect()
    assert connected is True
    await communicator.receive_json_from()  # subscribed

    layer = get_channel_layer()
    await layer.group_send(
        f"thread_{thread.pk}",
        {"type": "post.created", "post": {"id": post.pk, "body": "Привет"}},
    )

    message = await communicator.receive_json_from()
    assert message["type"] == "post.created"
    assert message["post"]["id"] == post.pk

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_notification_consumer_delivers(user):
    from channels.layers import get_channel_layer

    app = await _asgi_app(user)
    communicator = WebsocketCommunicator(app, "/ws/notifications/")
    connected, _ = await communicator.connect()
    assert connected is True

    initial = await communicator.receive_json_from()
    assert initial["type"] == "unread_count"

    layer = get_channel_layer()
    await layer.group_send(f"user_{user.pk}", {
        "type": "notification",
        "notification": {"id": 1, "kind": "reply", "payload": {}},
    })

    message = await communicator.receive_json_from()
    assert message["type"] == "notification"
    assert message["notification"]["kind"] == "reply"

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_presence_mark_online(user):
    from ws import presence

    await database_sync_to_async(presence.mark_online)(user.pk)
    assert await database_sync_to_async(presence.is_online)(user.pk) is True

    await database_sync_to_async(presence.mark_offline)(user.pk)
    assert await database_sync_to_async(presence.is_online)(user.pk) is False
