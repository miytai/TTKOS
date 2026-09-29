"""Аутентификация: refresh-токен в httpOnly-cookie (TECHSPEC §15.1)."""

from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken


class CookieJWTAuthentication(JWTAuthentication):
    """Поддерживает ``Authorization: Bearer`` и cookie с access-токеном.

    Refresh-токен хранится в httpOnly-cookie ``forumos_refresh`` и никогда
    не попадает в JavaScript (TECHSPEC §15.1).
    """

    def authenticate(self, request):
        header = self.get_header(request)
        if header is not None:
            return super().authenticate(request)

        raw_token = request.COOKIES.get("forumos_access")
        if not raw_token:
            return None

        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token

    def get_user(self, validated_token):
        try:
            user = super().get_user(validated_token)
        except InvalidToken:  # pragma: no cover - невалидный cookie
            return None
        if user is not None and user.is_banned:
            # Действующий бан отзывает доступ немедленно, не дожидаясь
            # истечения access-токена (TECHSPEC §4.10).
            from apps.moderation.models import Ban

            ban = Ban.active_for(user.pk)
            reason = ban.reason if ban and ban.reason else "нарушение правил"
            raise AuthenticationFailed(f"Аккаунт заблокирован: {reason}", code="account_banned")
        return user


def set_auth_cookies(response, access: str, refresh: str) -> None:
    """Установить httpOnly-cookie с токенами."""
    secure = getattr(settings, "JWT_REFRESH_COOKIE_SECURE", True)
    samesite = getattr(settings, "JWT_REFRESH_COOKIE_SAMESITE", "Lax")
    max_age_refresh = int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds())
    max_age_access = int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds())

    response.set_cookie(
        "forumos_access", access, httponly=True, secure=secure,
        samesite=samesite, max_age=max_age_access, path="/",
    )
    response.set_cookie(
        settings.JWT_REFRESH_COOKIE_NAME, refresh, httponly=True, secure=secure,
        samesite=samesite, max_age=max_age_refresh, path="/api/auth/",
    )


def clear_auth_cookies(response) -> None:
    """Удалить cookie с токенами (TECHSPEC §4.1 «Выход»)."""
    response.delete_cookie("forumos_access", path="/")
    response.delete_cookie(settings.JWT_REFRESH_COOKIE_NAME, path="/api/auth/")
