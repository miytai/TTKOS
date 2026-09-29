"""Уведомления (TECHSPEC §4.9, §16)."""

import pytest

from apps.notifications.models import Notification
from apps.notifications.services import (
    create_notification,
    mark_read,
    unread_count,
)


@pytest.mark.django_db
def test_create_notification_persists(user):
    created = create_notification(
        user_id=user.pk,
        kind="reply",
        payload={"actor_id": user.pk + 999, "thread_title": "Тема"},
    )

    assert created is not None
    assert Notification.objects.filter(user=user, is_read=False).count() == 1
    assert unread_count(user.pk) == 1


@pytest.mark.django_db
def test_no_notification_for_own_action(user):
    """О своих действиях не уведомляем (TECHSPEC §4.9)."""
    assert create_notification(
        user_id=user.pk, kind="reply", payload={"actor_id": user.pk}
    ) is None
    assert Notification.objects.count() == 0


@pytest.mark.django_db
def test_mark_read_updates_count(user):
    notification = create_notification(
        user_id=user.pk, kind="reply", payload={"actor_id": 100500}
    )

    mark_read(notification)
    notification.refresh_from_db()

    assert notification.is_read is True
    assert unread_count(user.pk) == 0


@pytest.mark.django_db
def test_notification_list_and_unread(auth_client, user):
    create_notification(user_id=user.pk, kind="reply", payload={"actor_id": 7})
    create_notification(user_id=user.pk, kind="like", payload={"actor_id": 8})

    listed = auth_client.get("/api/notifications/")
    assert listed.status_code == 200, listed.data
    assert len(listed.data["data"]) == 2

    unread = auth_client.get("/api/notifications/unread-count/")
    assert unread.status_code == 200, unread.data
    assert unread.data["data"]["count"] == 2

    first_pk = listed.data["data"][0]["id"]
    read = auth_client.post(f"/api/notifications/{first_pk}/read/")
    assert read.status_code == 200, read.data
    assert read.data["data"]["is_read"] is True

    after = auth_client.get("/api/notifications/unread-count/")
    assert after.data["data"]["count"] == 1


@pytest.mark.django_db
def test_notifications_require_auth(anon_client):
    response = anon_client.get("/api/notifications/")
    assert response.status_code in (401, 403)


@pytest.mark.django_db
def test_mark_all_read(auth_client, user):
    for actor in (1, 2, 3):
        create_notification(user_id=user.pk, kind="reply", payload={"actor_id": actor})

    response = auth_client.post("/api/notifications/read-all/")

    assert response.status_code == 200, response.data
    assert unread_count(user.pk) == 0
