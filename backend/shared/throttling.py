"""Rate limiting (TECHSPEC §5.4, §15.8).

Используется Redis-счётчик с окном: точность важнее «скользящих окон» DRF,
поэтому ограничения реализованы поверх django-redis совместимого клиента.
"""

import time

from rest_framework.exceptions import Throttled
from rest_framework.throttling import SimpleRateThrottle

from .logging import get_logger, security_log

logger = get_logger("forumos.throttle")

FAIL_LOG_LIMIT = 5  # после N превышений пишем в security-лог


class RedisWindowThrottle(SimpleRateThrottle):
    """Скользящее окно на Redis с журналированием превышений."""

    scope = "anon"

    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            ident = f"user:{user.pk}"
        else:
            ident = f"ip:{self.get_ident(request)}"
        self.ident = ident
        return self.cache_format % {"scope": self.scope, "ident": ident}

    def allow_request(self, request, view):
        allowed = super().allow_request(request, view)
        if not allowed:
            attempts = len(getattr(self, "history", []) or [])
            if attempts and attempts % self.num_requests == 0:
                security_log(
                    "rate_limit_exceeded",
                    scope=self.scope,
                    path=request.path,
                    ident=self.ident,
                )
        return allowed

    def throttled(self, request, wait):
        raise Throttled(detail="Слишком много запросов, попробуйте позже", wait=wait)

    def wait(self):
        """Время ожидания до конца окна (секунды)."""
        history = getattr(self, "history", []) or []
        if not history:
            return self.duration
        remaining = max(0.0, history[-1] - time.time())
        return int(remaining) + 1


class AnonRateThrottle(RedisWindowThrottle):
    """100 req/min на IP для анонимных пользователей."""

    scope = "anon"


class UserRateThrottle(RedisWindowThrottle):
    """60 req/min на авторизованного пользователя."""

    scope = "user"


class ContentCreationThrottle(RedisWindowThrottle):
    """30 req/min на создание контента (TECHSPEC §5.4)."""

    scope = "content"

    def allow_request(self, request, view):
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return True
        return super().allow_request(request, view)


class LoginRateThrottle(RedisWindowThrottle):
    """10 попыток входа в минуту на IP (TECHSPEC §4.1)."""

    scope = "login"


class RegisterRateThrottle(RedisWindowThrottle):
    """3 регистрации в час на IP."""

    scope = "register"


class EmailRateThrottle(RedisWindowThrottle):
    """3 письма в час на IP/email (подтверждение, сброс пароля)."""

    scope = "email"
