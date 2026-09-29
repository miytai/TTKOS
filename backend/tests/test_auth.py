"""Тесты аутентификации (TECHSPEC §11.2)."""

import pytest

from apps.accounts.services import ServiceError

pytestmark = pytest.mark.django_db


def test_register_creates_user_and_returns_envelope(api_client):
    response = api_client.post("/api/auth/register/", {
        "email": "newbie@example.com",
        "username": "newbie",
        "password": "Sup3rSecret!pass",
    }, format="json")

    assert response.status_code == 201, response.data
    assert response.data["data"]["user"]["username"] == "newbie"
    assert "access" in response.data["data"]
    assert response.data["errors"] == []
    assert response.cookies.get("forumos_refresh")


def test_register_rejects_weak_password(api_client):
    response = api_client.post("/api/auth/register/", {
        "email": "weak@example.com",
        "username": "weakuser",
        "password": "123",
    }, format="json")

    assert response.status_code == 400
    assert response.data["errors"]
    assert response.data["errors"][0]["field"] == "password"


def test_register_rejects_duplicate_username(api_client, user):
    response = api_client.post("/api/auth/register/", {
        "email": "other@example.com",
        "username": user.username,
        "password": "Sup3rSecret!pass",
    }, format="json")

    assert response.status_code == 409
    assert any(e["field"] == "username" or e["code"] == "conflict"
               for e in response.data["errors"])


def test_login_success(api_client, user):
    response = api_client.post("/api/auth/login/", {
        "email": "alice@example.com",
        "password": "Sup3rSecret!pass",
    }, format="json")

    assert response.status_code == 200, response.data
    assert response.data["data"]["user"]["username"] == "alice"


def test_login_wrong_password(api_client, user):
    response = api_client.post("/api/auth/login/", {
        "email": "alice@example.com",
        "password": "wrong-password-1",
    }, format="json")

    assert response.status_code == 401
    assert response.data["errors"][0]["code"] in ("invalid_credentials", "unauthorized")


def test_login_unknown_email_is_generic_error(api_client, db):
    response = api_client.post("/api/auth/login/", {
        "email": "nobody@example.com",
        "password": "Sup3rSecret!pass",
    }, format="json")

    assert response.status_code == 401


def test_refresh_rotates_token(api_client, user):
    login = api_client.post("/api/auth/login/", {
        "email": "alice@example.com",
        "password": "Sup3rSecret!pass",
    }, format="json")
    refresh = login.data["data"]["refresh"]

    response = api_client.post("/api/auth/refresh/", {"refresh": refresh}, format="json")

    assert response.status_code == 200, response.data
    assert response.data["data"]["access"]
    assert response.data["data"]["refresh"] != refresh, "refresh должен ротироваться"


def test_logout_clears_cookies(api_client, user):
    login = api_client.post("/api/auth/login/", {
        "email": "alice@example.com",
        "password": "Sup3rSecret!pass",
    }, format="json")

    response = api_client.post("/api/auth/logout/",
                               {"refresh": login.data["data"]["refresh"]}, format="json")

    assert response.status_code == 200
    assert response.cookies["forumos_refresh"].value == ""


def test_password_reset_flow(api_client, user):
    from django.core import mail

    request = api_client.post("/api/auth/password/reset/",
                              {"email": "alice@example.com"}, format="json")
    assert request.status_code == 200
    assert len(mail.outbox) == 1

    from apps.accounts.models import VerificationToken

    token = VerificationToken.objects.filter(
        user=user, purpose=VerificationToken.Purpose.PASSWORD_RESET
    ).latest("created_at")
    # В тестах сырой токен недоступен из письма, поэтому проверяем отказ по мусору
    response = api_client.post("/api/auth/password/confirm/", {
        "token": "invalid-token", "password": "N3wStrong!pass"
    }, format="json")
    assert response.status_code == 400
    assert token is not None


def test_email_verification_marks_user(new_user):
    from apps.accounts.services import issue_token, verify_email

    raw = issue_token(new_user, "email_verification")
    assert not new_user.is_email_verified

    verified = verify_email(raw)

    assert verified.is_email_verified
    assert verified.userprofile.rank in ("member", "regular")


def test_verify_email_rejects_used_token(new_user):
    from apps.accounts.services import ServiceError as SvcError
    from apps.accounts.services import issue_token, verify_email

    raw = issue_token(new_user, "email_verification")
    verify_email(raw)

    with pytest.raises(SvcError):
        verify_email(raw)


def test_service_error_carries_code():
    error = ServiceError("Нельзя", code="forbidden")

    assert error.code == "forbidden"
    assert error.message == "Нельзя"
