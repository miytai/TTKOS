"""Модерация: жалобы, баны, скрытие контента (TECHSPEC §4.10, §16)."""

import pytest
from rest_framework_simplejwt.tokens import RefreshToken

from apps.moderation.models import AuditLog, Ban
from apps.moderation.services import ModerationError, ban_user, hide_post
from apps.notifications.models import Notification
from tests.conftest import PASSWORD


def refresh_token_for(user) -> str:
    return RefreshToken.for_user(user).access_token


@pytest.mark.django_db
def test_user_can_flag_post(auth_client, post):
    response = auth_client.post("/api/moderation/flags/", {
        "target_type": "post",
        "target_id": post.pk,
        "reason": "spam",
        "comment": "Похоже на спам",
    }, format="json")

    assert response.status_code == 201, response.data
    assert response.data["data"]["status"] == "open"


@pytest.mark.django_db
def test_flag_requires_auth(anon_client, post):
    response = anon_client.post("/api/moderation/flags/", {
        "target_type": "post", "target_id": post.pk, "reason": "spam",
    }, format="json")

    assert response.status_code in (401, 403)


@pytest.mark.django_db
def test_moderator_resolves_flag(mod_client, auth_client, post):
    flag = auth_client.post("/api/moderation/flags/", {
        "target_type": "post", "target_id": post.pk, "reason": "spam",
    }, format="json")
    flag_id = flag.data["data"]["id"]

    response = mod_client.post(f"/api/moderation/flags/{flag_id}/resolve/",
                               {"comment": "Удалено"}, format="json")

    assert response.status_code == 200, response.data
    assert response.data["data"]["status"] == "resolved"
    assert response.data["data"]["resolved_by"]["username"] == "mod_octavian"


@pytest.mark.django_db
def test_regular_user_cannot_moderate(auth_client, post):
    response = auth_client.post("/api/moderation/audit-log/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_banned_user_cannot_login(api_client_factory, user, moderator):
    """Бан блокирует выдачу новых токенов (TECHSPEC §4.10)."""
    client = api_client_factory()
    ban_user(target_user=user, moderator=moderator, duration="1d", reason="flood")

    response = client.post("/api/auth/login/", {
        "email": "alice@example.com", "password": PASSWORD,
    }, format="json")

    assert response.status_code == 401, response.data
    assert response.data["errors"][0]["code"] == "account_banned"


@pytest.mark.django_db
def test_ban_revokes_existing_tokens(api_client_factory, user, moderator):
    """Действующий ban отзывает ранее выданный access-токен (TECHSPEC §4.10)."""
    client = api_client_factory()
    token = str(refresh_token_for(user))

    ban_user(target_user=user, moderator=moderator, duration="1d", reason="flood")

    response = client.get("/api/notifications/",
                          HTTP_AUTHORIZATION=f"Bearer {token}")

    assert response.status_code in (401, 403), response.data


@pytest.mark.django_db
def test_ban_blocks_moderation_endpoints(api_client_factory, user, moderator):
    """Забаненный не может жаловаться, пока бан активен (TECHSPEC §4.10)."""
    client = api_client_factory()
    ban_user(target_user=user, moderator=moderator, duration="1d", reason="flood")
    token = str(refresh_token_for(user))

    response = client.post("/api/moderation/flags/", {
        "target_type": "post", "target_id": 1, "reason": "spam",
    }, format="json", HTTP_AUTHORIZATION=f"Bearer {token}")

    assert response.status_code in (401, 403), response.data
    assert Ban.objects.filter(user=user, is_active=True).exists()


@pytest.mark.django_db
def test_ban_notification_created(user, moderator):
    ban_user(target_user=user, moderator=moderator, duration="7d", reason="flood")

    assert Notification.objects.filter(user=user, kind="system").exists()
    assert AuditLog.objects.filter(action=AuditLog.Action.BAN_USER).exists()


@pytest.mark.django_db
def test_cannot_ban_self(moderator):
    with pytest.raises(ModerationError):
        ban_user(target_user=moderator, moderator=moderator, duration="1d")


@pytest.mark.django_db
def test_hide_post_soft_deletes(post, moderator):
    hide_post(post, moderator, reason="спам")

    post.refresh_from_db()
    assert post.is_deleted is True
    assert AuditLog.objects.filter(action=AuditLog.Action.HIDE_POST).exists()


@pytest.mark.django_db
def test_moderation_hide_post_endpoint(mod_client, post):
    response = mod_client.post(f"/api/moderation/posts/{post.pk}/hide/",
                               {"reason": "спам"}, format="json")

    assert response.status_code == 200, response.data
    assert response.data["data"]["hidden"] is True
    post.refresh_from_db()
    assert post.is_deleted is True


@pytest.mark.django_db
def test_hide_post_requires_moderator(auth_client, other_user, post):
    response = auth_client.post(f"/api/moderation/posts/{post.pk}/hide/", {}, format="json")

    assert response.status_code == 403
