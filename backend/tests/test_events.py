"""Событийная шина: producer, outbox, handlers (TECHSPEC §13.2, §16)."""

import json

import pytest

from events import producer
from events.handlers import HANDLERS, track_analytics
from events.models import OutboxEvent


class _Msg:
    def __init__(self, topic: str, offset: int):
        self._topic = topic
        self._offset = offset

    def topic(self):
        return self._topic

    def offset(self):
        return self._offset


class FakeProducer:
    def __init__(self, fail: bool = False):
        self.messages = []
        self.fail = fail
        self.flushed = False
        self._callback = None

    def produce(self, topic, value, key=None, callback=None):
        if self.fail:
            raise RuntimeError("broker down")
        self.messages.append((topic, value, key))
        self._callback = callback

    def poll(self, timeout):
        return 0

    def flush(self, timeout=5):
        self.flushed = True
        if self._callback is not None and self.messages:
            self._callback(None, _Msg(self.messages[-1][0], len(self.messages)))


@pytest.mark.django_db
def test_producer_disabled_by_default(settings):
    settings.KAFKA_ENABLED = False
    assert producer.publish_event("post.created", {"post_id": 1}) is False
    assert OutboxEvent.objects.count() == 0


@pytest.mark.django_db
def test_topic_mapping(settings):
    settings.KAFKA_ENABLED = True
    assert producer.topic_for("post.created") == settings.KAFKA_TOPIC_POSTS
    assert producer.topic_for("thread.updated") == settings.KAFKA_TOPIC_THREADS
    assert producer.topic_for("user.registered") == settings.KAFKA_TOPIC_USERS
    assert producer.topic_for("moderation.flag") == settings.KAFKA_TOPIC_MODERATION
    assert producer.topic_for("unknown.event") == settings.KAFKA_TOPIC_DLQ


@pytest.mark.django_db
def test_publish_event_sends_envelope(settings, monkeypatch):
    settings.KAFKA_ENABLED = True
    fake = FakeProducer()
    monkeypatch.setattr(producer, "get_producer", lambda: fake)

    assert producer.publish_event("post.created", {"post_id": 3, "thread_id": 1}) is True

    topic, raw, _key = fake.messages[0]
    assert topic == settings.KAFKA_TOPIC_POSTS
    envelope = json.loads(raw.decode())
    assert envelope["event"] == "post.created"
    assert envelope["payload"]["post_id"] == 3
    assert envelope["version"] == 1


@pytest.mark.django_db
def test_failed_publish_falls_back_to_outbox(settings, monkeypatch):
    settings.KAFKA_ENABLED = True
    monkeypatch.setattr(producer, "get_producer", lambda: FakeProducer(fail=True))

    assert producer.publish_event("post.created", {"post_id": 9}) is False

    event = OutboxEvent.objects.get()
    assert event.event_name == "post.created"
    assert event.topic == settings.KAFKA_TOPIC_POSTS
    assert event.payload["post_id"] == 9
    assert not event.sent_at


@pytest.mark.django_db
def test_flush_outbox_sends_pending(settings, monkeypatch):
    from events.tasks import flush_outbox

    event = OutboxEvent.objects.create(event_name="post.created", topic="forumos.posts",
                                       payload={"post_id": 1})
    fake = FakeProducer()
    monkeypatch.setattr("events.producer.get_producer", lambda: fake)

    result = flush_outbox()

    assert result == {"sent": 1, "failed": 0}
    event.refresh_from_db()
    assert event.sent_at is not None
    assert len(fake.messages) == 1


@pytest.mark.django_db
def test_flush_outbox_marks_failure(settings, monkeypatch):
    from events.tasks import flush_outbox

    event = OutboxEvent.objects.create(event_name="post.created", topic="forumos.posts",
                                       payload={"post_id": 1})
    monkeypatch.setattr("events.producer.get_producer", lambda: FakeProducer(fail=True))

    result = flush_outbox()

    assert result == {"sent": 0, "failed": 1}
    event.refresh_from_db()
    assert event.attempts == 1
    assert event.last_error


@pytest.mark.django_db
def test_handler_routing_registry():
    for name in ("thread.created", "thread.deleted", "post.created", "post.deleted"):
        assert name in HANDLERS


@pytest.mark.django_db
def test_track_analytics_creates_event():
    from apps.analytics.models import EventLog

    track_analytics({"event_type": EventLog.Type.LOGIN, "payload": {"a": 1}})

    assert EventLog.objects.filter(event_type=EventLog.Type.LOGIN).count() == 1


@pytest.mark.django_db
def test_track_analytics_ignores_unknown_type():
    from apps.analytics.models import EventLog

    track_analytics({"event_type": "nope"})

    assert EventLog.objects.count() == 0


@pytest.mark.django_db
def test_index_handler_skips_without_elastic(thread, monkeypatch):
    from events.handlers import index_thread

    index_thread({"thread_id": thread.pk})  # не должно бросать исключение


@pytest.mark.django_db
def test_remove_post_handler_calls_delete(monkeypatch):
    from events import handlers

    calls = []
    monkeypatch.setattr("apps.search.service.delete_document", lambda e, i: calls.append((e, i)))
    handlers.remove_post({"post_id": 42})

    assert calls == [("posts", 42)]

@pytest.mark.django_db
def test_refresh_ranks_task(user):
    from apps.accounts.models import Rank
    from events.tasks import refresh_ranks

    user.userprofile.reputation = 5000
    user.userprofile.rank = Rank.NEWBIE
    user.userprofile.save()

    updated = refresh_ranks()

    user.userprofile.refresh_from_db()
    assert user.userprofile.rank == Rank.LEGEND
    assert updated >= 1
