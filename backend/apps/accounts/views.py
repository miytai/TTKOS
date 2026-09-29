"""Views аутентификации (TECHSPEC §11.2)."""

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from shared.authentication import clear_auth_cookies, set_auth_cookies
from shared.logging import get_logger
from shared.throttling import EmailRateThrottle, LoginRateThrottle, RegisterRateThrottle

from . import services
from .serializers import (
    EmailVerificationSerializer,
    LoginSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetSerializer,
    RegisterSerializer,
    UserSerializer,
)

logger = get_logger("forumos.auth")

UserModel = get_user_model()


def _tokens_for(user) -> dict:
    refresh = RefreshToken.for_user(user)
    refresh["username"] = user.username
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def _error(message: str, code: str = "error", field: str | None = None,
           http_status: int = status.HTTP_400_BAD_REQUEST):
    return Response(
        {"data": None, "meta": None,
         "errors": [{"code": code, "field": field, "message": message}]},
        status=http_status,
    )


class RegisterView(APIView):
    """``POST /api/auth/register/`` (TECHSPEC §4.1)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [RegisterRateThrottle]
    serializer_class = RegisterSerializer

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            user, raw_token = services.register_user(
                **serializer.validated_data, request=request
            )
        except services.ServiceError as exc:
            return _error(exc.message, exc.code, exc.field,
                          status.HTTP_409_CONFLICT if exc.code in
                          ("email_taken", "username_taken") else status.HTTP_400_BAD_REQUEST)

        services.send_verification_email(user, raw_token)
        tokens = _tokens_for(user)
        response = Response(
            {"data": {
                "user": UserSerializer(user).data,
                "is_email_verified": user.is_email_verified,
                "access": tokens["access"],
                "refresh": tokens["refresh"],
            }, "meta": {}, "errors": []},
            status=status.HTTP_201_CREATED,
        )
        set_auth_cookies(response, tokens["access"], tokens["refresh"])
        return response


class LoginView(APIView):
    """``POST /api/auth/login/`` (TECHSPEC §4.1)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [LoginRateThrottle]
    serializer_class = LoginSerializer

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            user = services.login_user(**serializer.validated_data, request=request)
        except services.ServiceError as exc:
            return _error(exc.message, exc.code, http_status=status.HTTP_401_UNAUTHORIZED)

        tokens = _tokens_for(user)
        response = Response(
            {"data": {
                "access": tokens["access"],
                "refresh": tokens["refresh"],
                "user": UserSerializer(user).data,
            }, "meta": {}, "errors": []},
            status=status.HTTP_200_OK,
        )
        # httpOnly-cookie дублируют тела ответа для SPA (TECHSPEC §15.1)
        set_auth_cookies(response, tokens["access"], tokens["refresh"])
        return response


class RefreshTokenView(APIView):
    """``POST /api/auth/refresh/`` — ротация refresh-токена (TECHSPEC §15.1)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    serializer_class = None

    def post(self, request):
        from rest_framework_simplejwt.exceptions import TokenError
        from rest_framework_simplejwt.tokens import RefreshToken

        raw = (
            request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)
            or request.data.get("refresh")
        )
        if not raw:
            return _error("Refresh-токен не передан", code="token_required", field="refresh",
                          http_status=status.HTTP_401_UNAUTHORIZED)
        try:
            old_refresh = RefreshToken(raw)
            user = UserModel.objects.get(pk=old_refresh["user_id"])
            if old_refresh.check_blacklist():
                return _error("Refresh-токен уже использован", code="token_revoked",
                              field="refresh", http_status=status.HTTP_401_UNAUTHORIZED)
            new_access = str(old_refresh.access_token)
            # Ротация: клиенту выдаётся новый refresh со своим jti
            new_refresh = RefreshToken.for_user(user)
            new_refresh["username"] = user.username
            old_refresh.blacklist()
        except (TokenError, UserModel.DoesNotExist, KeyError):
            return _error("Недействительный или истёкший refresh-токен",
                          code="invalid_token", field="refresh",
                          http_status=status.HTTP_401_UNAUTHORIZED)

        logger.info("token_refreshed", user_id=user.pk)
        response = Response(
            {"data": {"access": new_access, "refresh": str(new_refresh)},
             "meta": {}, "errors": []},
            status=status.HTTP_200_OK,
        )
        set_auth_cookies(response, new_access, str(new_refresh))
        return response


class LogoutView(APIView):
    """``POST /api/auth/logout/`` — отзыв refresh и очистка cookies (TECHSPEC §4.1)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        raw = (request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)
               or request.data.get("refresh"))
        if raw:
            from rest_framework_simplejwt.exceptions import TokenError
            from rest_framework_simplejwt.tokens import RefreshToken

            try:
                RefreshToken(raw).blacklist()
            except TokenError:
                pass  # токен уже отозван — выход всё равно успешен

        response = Response({"data": {"detail": "Вы вышли из аккаунта"},
                             "meta": {}, "errors": []}, status=status.HTTP_200_OK)
        clear_auth_cookies(response)
        if request.user.is_authenticated:
            logger.info("logout", user_id=request.user.pk)
        return response


class PasswordResetView(APIView):
    """``POST /api/auth/password/reset/`` (TECHSPEC §4.1)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [EmailRateThrottle]
    serializer_class = PasswordResetSerializer

    def post(self, request):
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.request_password_reset(serializer.validated_data["email"], request=request)
        # Ответ одинаков для существующих и несуществующих email
        return Response(
            {"data": {"detail": "Если аккаунт существует, письмо с инструкцией отправлено"},
             "meta": {}, "errors": []},
            status=status.HTTP_200_OK,
        )


class PasswordResetConfirmView(APIView):
    """``POST /api/auth/password/confirm/`` (TECHSPEC §4.1)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    serializer_class = PasswordResetConfirmSerializer

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = services.confirm_password_reset(
                serializer.validated_data["token"], serializer.validated_data["new_password"]
            )
        except services.ServiceError as exc:
            return _error(exc.message, exc.code, exc.field)

        response = Response(
            {"data": {"detail": "Пароль обновлён"}, "email": user.email,
             "meta": {}, "errors": []},
            status=status.HTTP_200_OK,
        )
        clear_auth_cookies(response)
        return response


class EmailVerificationView(APIView):
    """``POST /api/auth/verify-email/`` (TECHSPEC §4.1)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    serializer_class = EmailVerificationSerializer

    def post(self, request):
        serializer = EmailVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = services.verify_email(serializer.validated_data["token"])
        except services.ServiceError as exc:
            return _error(exc.message, exc.code, exc.field)

        response = Response(
            {"data": {"detail": "Email подтверждён", "username": user.username,
                      "is_email_verified": True},
             "meta": {}, "errors": []},
            status=status.HTTP_200_OK,
        )
        tokens = _tokens_for(user)
        set_auth_cookies(response, tokens["access"], tokens["refresh"])
        return response


class ResendVerificationView(APIView):
    """``POST /api/auth/resend-verification/`` — не чаще 3 раз в час (TECHSPEC §4.1)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [EmailRateThrottle]

    def post(self, request):
        user = request.user if request.user.is_authenticated else None
        email = (request.data or {}).get("email")
        if user is None and email:
            user = UserModel.objects.filter(email__iexact=email.strip()).first()

        if user is None:
            return _error("Пользователь не найден", code="user_not_found", field="email",
                          http_status=status.HTTP_404_NOT_FOUND)

        try:
            services.resend_verification(user)
        except services.ServiceError as exc:
            return _error(exc.message, exc.code, exc.field)
        return Response({"data": {"detail": "Письмо отправлено"}, "meta": {}, "errors": []})


class MeView(APIView):
    """``GET /api/users/me/`` — быстрый текущий пользователь."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .serializers import UserMeSerializer

        services.touch_last_seen(request.user.pk)
        return Response({"data": UserMeSerializer(request.user).data,
                         "meta": {}, "errors": []})
