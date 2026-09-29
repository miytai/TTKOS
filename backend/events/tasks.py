"""Периодические задачи событийной шины (TECHSPEC §13.2)."""

from __future__ import annotations

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from shared.logging import get_logger

logger = get_logger("forumos.events.tasks")

OUTBOX_BATCH = 200


@shared_task(name="events.tasks.flush_outbox")
def flush_outbox(limit: int = OUTBOX_BATCH) -> dict:
    """Повторно отправить накопленные в outbox события (TECHSPEC §13.2)."""
    from events.models import OutboxEvent
    from events.producer import get_producer

    pending = list(
        OutboxEvent.objects.filter(sent_at__isnull=True)
        .order_by("created_at")[:limit]
    )
    if not pending:
        return {"sent": 0, "failed": 0}

    producer = get_producer()
    if producer is None:
        logger.info("outbox_flush_skipped", reason="kafka_disabled", pending=len(pending))
        return {"sent": 0, "failed": 0}

    import json

    sent = failed = 0
    for event in pending:
        try:
            envelope = {
                "event": event.event_name,
                "version": 1,
                "payload": event.payload,
            }
            producer.produce(
                topic=event.topic,
                value=json.dumps(envelope, ensure_ascii=False, default=str).encode("utf-8"),
            )
            producer.poll(0)
            event.mark_sent()
            sent += 1
        except Exception as exc:  # pragma: no cover - брокер недоступен
            event.mark_failed(str(exc))
            failed += 1
            logger.warning("outbox_event_failed", event_id=event.pk, error=str(exc)[:200])
    producer.flush(timeout=5)
    logger.info("outbox_flushed", sent=sent, failed=failed)
    return {"sent": sent, "failed": failed}


@shared_task(name="events.tasks.refresh_ranks")
def refresh_ranks() -> int:
    """Пересчитать звания по текущей репутации (TECHSPEC §4.6)."""
    from apps.accounts.models import UserProfile, rank_for_reputation

    updated = 0
    queryset = UserProfile.objects.exclude(rank="moderator").only(
        "id", "user_id", "reputation", "rank"
    )
    for profile in queryset.iterator(chunk_size=500):
        expected = rank_for_reputation(profile.reputation)
        if profile.rank != expected:
            profile.rank = expected
            profile.save(update_fields=["rank", "updated_at"])
            updated += 1
    if updated:
        logger.info("ranks_refreshed", updated=updated)
    return updated


@shared_task(name="events.tasks.cleanup_expired_tokens")
def cleanup_expired_tokens() -> int:
    """Удалить просроченные записи blacklist JWT (TECHSPEC §4.10)."""
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    now = timezone.now()
    expired_ids = list(
        OutstandingToken.objects.filter(expires_at__lt=now).values_list("pk", flat=True)[:5000]
    )
    if not expired_ids:
        return 0
    with transaction.atomic():
        BlacklistedToken.objects.filter(token_id__in=expired_ids).delete()
        OutstandingToken.objects.filter(pk__in=expired_ids).delete()
    logger.info("expired_tokens_cleaned", count=len(expired_ids))
    return len(expired_ids)
