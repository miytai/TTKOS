"""ASGI-точка входа: HTTP через Django, WebSocket через Channels (TECHSPEC §6.1)."""

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

# Django должен быть инициализирован до импорта потребителей (модели, apps).
django_asgi_app = get_asgi_application()

from ws.middleware import JWTAuthMiddleware, UserBanMiddleware  # noqa: E402
from ws.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": UserBanMiddleware(
            JWTAuthMiddleware(URLRouter(websocket_urlpatterns))
        ),
    }
)
