"""Presence: кто онлайн (TECHSPEC §6.4).

Состояние держится в Redis с TTL, поэтому перезапуск не оставляет «мёртвых»
пользователей в списке онлайн.
"""

from __future__ import annotations

import time

from django.conf import settings

from shared.logging import get_logger

logger = get_logger("forumos.presence")

PRESENCE_TTL = 300  # секунд


def _key(user_id: int) -> str:
    return f"presence:user:{user_id}"


def mark_online(user_id: int) -> None:
    """Отметить пользователя онлайн."""
    from django.core.cache import cache

    cache.set(_key(user_id), int(time.time()), timeout=PRESENCE_TTL)


def mark_offline(user_id: int, thread_id: int | None = None) -> None:
    """Снять отметку онлайн."""
    from django.core.cache import cache

    cache.delete(_key(user_id))


def is_online(user_id: int) -> bool:
    from django.core.cache import cache

    return cache.get(_key(user_id)) is not None


def is_user_online(user_id: int) -> bool:
    """Совместимое имя для вызовов из моделей (TECHSPEC §6.4)."""
    return is_online(user_id)


def online_users() -> list[dict]:
    """Список онлайн-пользователей (TECHSPEC §6.4)."""
    from django.core.cache import cache
    from django_redis import get_redis_connection

    try:
        client = get_redis_connection(cache)
        keys = list(client.scan_iter(match="presence:user:*", count=200))
        if not keys:
            return []
        values = client.mget(keys)
        now = int(time.time())
        users = []
        for key, value in zip(keys, values, strict=False):
            if value is None:
                continue
            user_id = int(key.decode().rsplit(":", 1)[-1])
            users.append({"user_id": user_id, "last_seen": int(value), "age": now - int(value)})
        return users
    except Exception as exc:  # pragma: no cover - Redis недоступен
        logger.warning("presence_scan_failed", error=str(exc)[:200])
        return []


def cleanup_stale(max_age: int = PRESENCE_TTL) -> int:
    """Удалить протухшие записи presence (TECHSPEC §6.4)."""
    from django.core.cache import cache
    from django_redis import get_redis_connection

    removed = 0
    try:
        client = get_redis_connection(cache)
        now = int(time.time())
        for key in client.scan_iter(match="presence:user:*", count=200):
            value = client.get(key)
            if value is None or now - int(value) > max_age:
                client.delete(key)
                removed += 1
    except Exception as exc:  # pragma: no cover
        logger.warning("presence_cleanup_failed", error=str(exc)[:200])
    return removed


def presence_settings() -> dict:
    cache_location = getattr(settings, "CACHES", {}).get("default", {}).get("LOCATION", "locmem")
    return {"ttl": PRESENCE_TTL, "backend": cache_location}
