"""Аналитика: приём событий, heatmap, статистика (TECHSPEC §4.2, §10.2, §16)."""

import pytest

from apps.analytics.models import EventLog


@pytest.mark.django_db
def test_ingest_event_as_anon(anon_client):
    response = anon_client.post("/api/analytics/events/", {
        "event_type": EventLog.Type.PAGE_VIEW,
        "payload": {"path": "/f/dev"},
    }, format="json")

    assert response.status_code == 202, response.data
    assert response.data["data"]["accepted"] is True
    assert EventLog.objects.filter(event_type=EventLog.Type.PAGE_VIEW).count() == 1


@pytest.mark.django_db
def test_ingest_rejects_unknown_type(anon_client):
    response = anon_client.post("/api/analytics/events/", {"event_type": "nonsense"},
                                format="json")

    assert response.status_code == 400
    assert response.data["errors"]


@pytest.mark.django_db
def test_ingest_stores_ip_and_agent(anon_client):
    anon_client.post("/api/analytics/events/", {
        "event_type": EventLog.Type.SEARCH,
        "payload": {"q": "docker"},
    }, format="json", HTTP_USER_AGENT="ForumOS-Test/1.0")

    event = EventLog.objects.get(event_type=EventLog.Type.SEARCH)
    assert event.user_agent == "ForumOS-Test/1.0"
    assert event.ip is not None


@pytest.mark.django_db
def test_heatmap_for_authenticated_user(auth_client, user):
    EventLog.track(event_type=EventLog.Type.PAGE_VIEW, user=user)
    EventLog.track(event_type=EventLog.Type.PAGE_VIEW, user=user)

    response = auth_client.get("/api/analytics/heatmap/?days=30")

    assert response.status_code == 200, response.data
    assert response.data["meta"]["days"] == 30
    assert response.data["data"][0]["count"] == 2


@pytest.mark.django_db
def test_heatmap_by_username(anon_client, user):
    EventLog.track(event_type=EventLog.Type.THREAD_VIEW, user=user)

    response = anon_client.get(f"/api/analytics/heatmap/?username={user.username}")

    assert response.status_code == 200, response.data
    assert sum(item["count"] for item in response.data["data"]) == 1


@pytest.mark.django_db
def test_heatmap_anonymous_without_username_is_empty(anon_client):
    response = anon_client.get("/api/analytics/heatmap/")

    assert response.status_code == 200
    assert response.data["data"] == []


@pytest.mark.django_db
def test_heatmap_unknown_username(anon_client):
    response = anon_client.get("/api/analytics/heatmap/?username=ghost")

    assert response.status_code == 200
    assert response.data["data"] == []


@pytest.mark.django_db
def test_heatmap_caps_days(anon_client, user):
    EventLog.track(event_type=EventLog.Type.PAGE_VIEW, user=user)

    response = anon_client.get(f"/api/analytics/heatmap/?username={user.username}&days=99999")

    assert response.data["meta"]["days"] == 1095


@pytest.mark.django_db
def test_user_stats_public(anon_client, user):
    response = anon_client.get(f"/api/analytics/users/{user.pk}/stats/")

    assert response.status_code == 200, response.data
    assert response.data["data"]["reputation"] == 120


@pytest.mark.django_db
def test_user_stats_missing_user(anon_client):
    response = anon_client.get("/api/analytics/users/999999/stats/")

    assert response.status_code == 404
    assert response.data["errors"][0]["code"] == "not_found"


@pytest.mark.django_db
def test_admin_stats_requires_moderator(auth_client, mod_client, thread, post):
    assert auth_client.get("/api/analytics/stats/").status_code == 403

    response = mod_client.get("/api/analytics/stats/")

    assert response.status_code == 200, response.data
    assert response.data["data"]["threads"] == 1
    assert response.data["data"]["posts"] == 1
    assert response.data["meta"]["period_days"] == 30
