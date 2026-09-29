"""Kafka producer (TECHSPEC §13.1).

Публикация синхронная с безопасным фолбэком: если Kafka недоступна, событие
пишется в outbox-очередь и будет отправлено позже.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from django.conf import settings

from shared.logging import get_logger

logger = get_logger("forumos.events")

_producer = None
_lock = threading.Lock()


def get_producer():
    """Ленивая инициализация KafkaProducer (TECHSPEC §13.1)."""
    global _producer
    if _producer is not None:
        return _producer
    if not getattr(settings, "KAFKA_ENABLED", False):
        return None

    with _lock:
        if _producer is not None:
            return _producer
        try:
            from confluent_kafka import Producer
        except ImportError:  # pragma: no cover
            logger.warning("kafka_package_missing")
            return None
        try:
            _producer = Producer({
                "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
                "client.id": settings.KAFKA_CLIENT_ID,
                "compression.type": "snappy",
                "acks": "1",
                "linger.ms": 5,
                "message.timeout.ms": 4000,
            })
            logger.info("kafka_producer_initialized",
                        servers=settings.KAFKA_BOOTSTRAP_SERVERS)
        except Exception as exc:  # pragma: no cover
            logger.error("kafka_producer_init_failed", error=str(exc)[:300])
            _producer = None
    return _producer


def topic_for(event_name: str) -> str:
    """Топик по имени события (TECHSPEC §13.1)."""
    for prefix, topic in (
        ("post.", settings.KAFKA_TOPIC_POSTS),
        ("thread.", settings.KAFKA_TOPIC_THREADS),
        ("user.", settings.KAFKA_TOPIC_USERS),
        ("notification.", settings.KAFKA_TOPIC_NOTIFICATIONS),
        ("moderation.", settings.KAFKA_TOPIC_MODERATION),
        ("analytics.", settings.KAFKA_TOPIC_ANALYTICS),
    ):
        if event_name.startswith(prefix):
            return topic
    return settings.KAFKA_TOPIC_DLQ


def publish_event(event_name: str, payload: dict[str, Any], *, key: str | None = None) -> bool:
    """Опубликовать доменное событие (TECHSPEC §13.1).

    Возвращает ``True``, если событие ушло в Kafka, ``False`` — если записано
    в outbox для повторной отправки.
    """
    if not getattr(settings, "KAFKA_ENABLED", False):
        return False

    producer = get_producer()
    topic = topic_for(event_name)

    if producer is None:
        _save_outbox(event_name, topic, payload)
        return False

    envelope = {
        "event": event_name,
        "version": 1,
        "source": settings.KAFKA_CLIENT_ID,
        "key": key or str(payload.get("thread_id") or payload.get("user_id") or ""),
        "payload": payload,
    }
    message = json.dumps(envelope, ensure_ascii=False, default=str).encode("utf-8")

    delivered: dict = {"err": "not flushed"}

    def _on_delivery(err, msg, delivered=delivered, event_name=event_name,
                     topic=topic, payload=payload):
        if err is not None:
            delivered["err"] = str(err)
            logger.warning("kafka_delivery_failed",
                           event_name=event_name, error=str(err)[:200])
        else:
            delivered["err"] = None
            logger.debug("kafka_delivered", topic=msg.topic(), offset=msg.offset())

    try:
        producer.produce(
            topic=topic,
            key=envelope["key"].encode("utf-8") or None,
            value=message,
            callback=_on_delivery,
        )
    except BufferError:
        producer.flush(timeout=5)
        producer.produce(
            topic=topic, value=message,
            key=envelope["key"].encode("utf-8") or None,
            callback=_on_delivery,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("kafka_publish_failed", event_name=event_name, error=str(exc)[:200])
        _save_outbox(event_name, topic, payload)
        return False

    # Дожидаемся доставки, чтобы успеть записать в outbox при сбое (TECHSPEC §13.2).
    producer.flush(timeout=2.0)
    if delivered["err"] is not None:
        _save_outbox(event_name, topic, payload)
        return False
    return True


def _save_outbox(event_name: str, topic: str, payload: dict) -> None:
    """Сохранить событие в БД для повторной доставки (TECHSPEC §13.2)."""
    from events.models import OutboxEvent

    try:
        OutboxEvent.objects.create(
            event_name=event_name[:100],
            topic=topic[:100],
            payload=payload,
        )
    except Exception as exc:  # pragma: no cover - таблицы может не быть
        logger.warning("kafka_outbox_write_failed", event_name=event_name, error=str(exc)[:200])


def flush(timeout: float = 5.0) -> None:
    producer = get_producer()
    if producer is not None:
        producer.flush(timeout=timeout)


def producer_health(timeout: float = 2.0) -> bool:
    """Доступен ли брокер: запрашиваем метаданные кластера (TECHSPEC §5.3)."""
    producer = get_producer()
    if producer is None:
        return False
    try:
        metadata = producer.list_topics(timeout=timeout)
    except Exception as exc:  # pragma: no cover — брокер недоступен
        logger.warning("kafka_health_check_failed", error=str(exc)[:200])
        return False
    return bool(metadata.brokers)
