"""Celery-задачи индексации Elasticsearch (TECHSPEC §4.7)."""

from celery import shared_task

from shared.logging import get_logger

from . import service

logger = get_logger("forumos.search.tasks")

BATCH_SIZE = 500


@shared_task(name="search.reindex_all", bind=True, max_retries=3, default_retry_delay=60)
def reindex_all(self, entity: str | None = None) -> dict:
    """Полная переиндексация (TECHSPEC §5.3)."""
    from apps.accounts.models import User
    from apps.posts.models import Post
    from apps.threads.models import Thread

    service.ensure_indices()
    stats = {"threads": 0, "posts": 0, "users": 0}

    if entity in (None, "", "threads"):
        queryset = Thread.objects.select_related("forum", "author").prefetch_related("tags")
        stats["threads"] = _index_queryset(queryset, "threads", service.thread_document)

    if entity in (None, "", "posts"):
        queryset = Post.objects.select_related("thread", "thread__forum", "author")
        stats["posts"] = _index_queryset(queryset, "posts", service.post_document)

    if entity in (None, "", "users"):
        queryset = User.objects.select_related("userprofile")
        stats["users"] = _index_queryset(queryset, "users", service.user_document)

    service.refresh_indices()
    logger.info("search_reindex_done", **stats)
    return stats


def _index_queryset(queryset, entity: str, builder) -> int:
    """Индексировать queryset пачками, не загружая таблицу целиком в память."""
    pks = list(queryset.values_list("pk", flat=True))
    indexed = 0
    for start in range(0, len(pks), BATCH_SIZE):
        batch_pks = pks[start:start + BATCH_SIZE]
        for obj in queryset.model.objects.filter(pk__in=batch_pks):
            if service.index_document(entity, obj.pk, builder(obj)):
                indexed += 1
    return indexed


@shared_task(name="search.purge_old")
def purge_old(days: int = 30) -> int:
    """Удалить старые документы из индексов (TECHSPEC §5.3)."""
    deleted = service.purge_old_documents(days)
    logger.info("search_purge_done", deleted=deleted)
    return deleted
