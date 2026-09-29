"""Kafka consumer: обработка доменных событий (TECHSPEC §13.2)."""

from __future__ import annotations

import json
import signal

from django.conf import settings
from django.db import close_old_connections

from shared.logging import get_logger

logger = get_logger("forumos.events.consumer")

_consumer = None
_running = True


def get_consumer():
    global _consumer
    if _consumer is not None:
        return _consumer
    if not getattr(settings, "KAFKA_ENABLED", False):
        return None
    try:
        from confluent_kafka import Consumer
    except ImportError:  # pragma: no cover
        logger.warning("kafka_package_missing")
        return None
    _consumer = Consumer({
        "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
        "group.id": settings.KAFKA_CONSUMER_GROUP,
        "client.id": f"{settings.KAFKA_CLIENT_ID}-consumer",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })
    return _consumer


def subscribed_topics() -> list[str]:
    """Топики, которые обрабатывает бэкенд (TECHSPEC §13.1)."""
    return [
        settings.KAFKA_TOPIC_POSTS,
        settings.KAFKA_TOPIC_THREADS,
        settings.KAFKA_TOPIC_USERS,
        settings.KAFKA_TOPIC_NOTIFICATIONS,
        settings.KAFKA_TOPIC_MODERATION,
    ]


def _handle(envelope: dict) -> None:
    """Маршрутизация события в обработчик."""
    from .handlers import HANDLERS

    event = envelope.get("event", "")
    handler = HANDLERS.get(event)
    if handler is None:
        logger.debug("kafka_event_unhandled", event_name=event)
        return
    try:
        handler(envelope.get("payload") or {})
    except Exception as exc:  # pragma: no cover
        logger.error("kafka_handler_failed", event_name=event, error=str(exc)[:300])
        raise


def _stop(signum, frame) -> None:  # pragma: no cover
    global _running
    logger.info("kafka_consumer_stopping", signal=signum)
    _running = False


def run_forever() -> None:  # pragma: no cover - бесконечный цикл
    """Основной цикл consumer (TECHSPEC §13.2)."""
    consumer = get_consumer()
    if consumer is None:
        logger.info("kafka_consumer_disabled")
        return

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    consumer.subscribe(subscribed_topics())
    logger.info("kafka_consumer_started", topics=subscribed_topics())

    try:
        while _running:
            message = consumer.poll(1.0)
            if message is None:
                continue
            if message.error():
                logger.warning("kafka_message_error", error=str(message.error())[:200])
                continue
            try:
                envelope = json.loads(message.value().decode("utf-8"))
                _handle(envelope)
                consumer.commit()
            except json.JSONDecodeError as exc:
                logger.error("kafka_bad_json", error=str(exc)[:200])
                consumer.commit()
            finally:
                close_old_connections()
    finally:
        consumer.close()
        logger.info("kafka_consumer_stopped")
