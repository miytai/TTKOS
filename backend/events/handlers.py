"""Обработчики доменных событий (TECHSPEC §13.2).

Индексация в Elasticsearch, аналитика и очистка кэшей выполняются
асинхронно из Kafka, а не в HTTP-запросе.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from django.utils import timezone

std_logger = logging.getLogger("forumos.events.handlers")


def index_thread(payload: dict[str, Any]) -> None:
    """Проиндексировать тему после публикации (TECHSPEC §4.7)."""
    from apps.search.service import get_client, index_document, thread_document
    from apps.threads.models import Thread

    if get_client() is None:
        return
    thread = Thread.objects.filter(pk=payload.get("thread_id")).first()
    if thread is not None:
        index_document("threads", thread.pk, thread_document(thread))


def index_post(payload: dict[str, Any]) -> None:
    """Проиндексировать пост (TECHSPEC §4.7)."""
    from apps.posts.models import Post
    from apps.search.service import get_client, index_document, post_document

    if get_client() is None:
        return
    post = Post.objects.select_related("thread", "author").filter(
        pk=payload.get("post_id")
    ).first()
    if post is not None:
        index_document("posts", post.pk, post_document(post))


def remove_post(payload: dict[str, Any]) -> None:
    """Убрать пост из индекса при удалении (TECHSPEC §5.3)."""
    from apps.search.service import delete_document

    delete_document("posts", payload.get("post_id"))


def remove_thread(payload: dict[str, Any]) -> None:
    """Убрать тему из индекса при удалении (TECHSPEC §5.3)."""
    from apps.search.service import delete_document

    delete_document("threads", payload.get("thread_id"))


def track_analytics(payload: dict[str, Any]) -> None:
    """Записать событие аналитики из домена (TECHSPEC §10.2)."""
    from apps.analytics.models import EventLog

    event_type = payload.get("event_type")
    if not event_type or event_type not in EventLog.Type.values:
        return
    EventLog.objects.create(
        event_type=event_type,
        payload=payload.get("payload") or {},
        created_at=payload.get("at") or timezone.now(),
    )


def warm_search(payload: dict[str, Any]) -> None:
    """Обновить индекс темы после изменения счётчиков (TECHSPEC §4.7)."""
    from apps.search.service import get_client, index_document, thread_document
    from apps.threads.models import Thread

    if get_client() is None:
        return
    thread = Thread.objects.filter(pk=payload.get("thread_id")).first()
    if thread is not None:
        index_document("threads", thread.pk, thread_document(thread), refresh=True)


HANDLERS: dict[str, Callable[[dict], None]] = {
    "thread.created": index_thread,
    "thread.updated": index_thread,
    "thread.deleted": remove_thread,
    "thread.activity": warm_search,
    "post.created": index_post,
    "post.updated": index_post,
    "post.deleted": remove_post,
    "user.registered": track_analytics,
}
