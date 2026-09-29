"""JWT-аутентификация для WebSocket (TECHSPEC §6.1)."""

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware


@database_sync_to_async
def _get_user(token: str):
    """Разрешить пользователя по access-токену."""
    if not token:
        return None
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.tokens import AccessToken

    try:
        return AccessToken(token).user
    except TokenError:
        return None
    except Exception:  # pragma: no cover
        return None


class JWTAuthMiddleware(BaseMiddleware):
    """Аутентификация WS по ``?token=<access>`` или куке (TECHSPEC §6.1)."""

    async def __call__(self, scope, receive, send):
        scope = dict(scope)
        token = self._extract_token(scope)
        user = await _get_user(token) if token else None
        scope["user"] = user
        return await super().__call__(scope, receive, send)

    @staticmethod
    def _extract_token(scope) -> str:
        query = parse_qs((scope.get("query_string") or b"").decode("utf-8"))
        if token := query.get("token", [None])[0]:
            return token
        return _cookie_from_headers(scope.get("headers") or []).get("access_token", "")


def _cookie_from_headers(headers) -> dict:
    """Разобрать заголовок Cookie в словарь."""
    cookies: dict[str, str] = {}
    for name, value in headers:
        if name != b"cookie":
            continue
        for part in value.decode("utf-8", "ignore").split(";"):
            if "=" in part:
                key, _, val = part.partition("=")
                cookies[key.strip()] = val.strip()
    return cookies


class UserBanMiddleware(BaseMiddleware):
    """Закрыть соединение для забаненных пользователей (TECHSPEC §6.1)."""

    async def __call__(self, scope, receive, send):
        scope = dict(scope)
        user = scope.get("user")
        if user is not None and getattr(user, "is_authenticated", False):
            banned = await self._is_banned(user.pk)
            scope["user"] = None if banned else user
            scope["is_banned"] = banned
        return await super().__call__(scope, receive, send)

    @staticmethod
    @database_sync_to_async
    def _is_banned(user_id: int) -> bool:
        from apps.moderation.models import Ban

        return Ban.objects.filter(user_id=user_id).active().exists()
