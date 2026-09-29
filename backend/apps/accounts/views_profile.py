"""API профилей пользователей (TECHSPEC §11.3)."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from shared.logging import get_logger
from shared.utils import client_ip

from . import services
from .models import Achievement, UserAchievement, UserProfile
from .serializers import (
    AccountDeleteSerializer,
    AchievementSerializer,
    PasswordChangeSerializer,
    UserMeSerializer,
    UserSerializer,
    UserUpdateSerializer,
)

logger = get_logger("forumos.accounts")

UserModel = get_user_model()


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    """``/api/users/`` — список, профиль, активность, настройки (TECHSPEC §4.2)."""

    queryset = UserModel.objects.filter(is_deleted=False).select_related("userprofile")
    serializer_class = UserSerializer
    lookup_field = "username"
    lookup_value_regex = r"[\w.@+-]+"
    permission_classes = [AllowAny]
    filterset_fields = ["is_email_verified"]
    search_fields = ["username"]
    ordering_fields = ["created_at", "username"]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == "list":
            qs = qs.order_by("-userprofile__reputation", "-date_joined")
        return qs

    def retrieve(self, request, *args, **kwargs):
        """Профиль пользователя + ачивки (TECHSPEC §4.2)."""
        user = self.get_object()
        unlocked = {
            ua.achievement_id: ua
            for ua in UserAchievement.objects.filter(user=user).select_related("achievement")
        }
        data = UserSerializer(user, context={"request": request}).data
        data["achievements"] = AchievementSerializer(
            Achievement.objects.all(),
            many=True,
            context={
                "unlocked_ids": set(unlocked.keys()),
                "unlocked_map": {aid: ua.unlocked_at for aid, ua in unlocked.items()},
            },
        ).data
        data["stats"] = self._stats(user)
        return Response({"data": data, "meta": {}, "errors": []})

    @staticmethod
    def _stats(user) -> dict:
        from apps.posts.models import Post
        from apps.threads.models import Thread

        threads = Thread.objects.filter(author=user, is_deleted=False).count()
        posts = Post.objects.filter(author=user, is_deleted=False).count()
        reactions = (
            Post.objects.filter(author=user, is_deleted=False)
            .aggregate(total=Sum("reactions_count"))["total"] or 0
        )
        return {"threads": threads, "posts": posts, "reactions": reactions}

    @action(detail=True, methods=["get"])
    def threads(self, request, username=None):
        """Темы пользователя."""
        from apps.threads.models import Thread
        from apps.threads.serializers import ThreadListSerializer

        user = self.get_object()
        qs = Thread.objects.filter(author=user, is_deleted=False).select_related(
            "forum", "author"
        )
        page = self.paginate_queryset(qs)
        serializer = ThreadListSerializer(page, many=True, context={"request": request})
        return self.get_paginated_response(serializer.data)

    @action(detail=True, methods=["get"])
    def posts(self, request, username=None):
        """Посты пользователя."""
        from apps.posts.models import Post
        from apps.posts.serializers import PostSerializer

        user = self.get_object()
        qs = Post.objects.filter(author=user, is_deleted=False).select_related(
            "thread", "author"
        )
        page = self.paginate_queryset(qs)
        serializer = PostSerializer(page, many=True, context={"request": request})
        return self.get_paginated_response(serializer.data)

    @action(detail=True, methods=["get"], url_path="activity")
    def activity(self, request, username=None):
        """Heatmap активности по дням за год (TECHSPEC §4.2)."""
        user = self.get_object()
        from apps.analytics.models import EventLog

        since = timezone.now() - timedelta(days=365)
        rows = (
            EventLog.objects.filter(user=user, created_at__gte=since)
            .extra(select={"day": "created_at::date"})
            .values("day")
            .annotate(count=Count("id"))
            .order_by("day")
        )
        activity = [
            {"date": str(row["day"]), "count": row["count"]} for row in rows
        ]
        return Response({"data": {"user": username, "activity": activity},
                         "meta": {}, "errors": []})

    # ── Свой профиль ─────────────────────────────────────────────
    @action(detail=False, methods=["get", "patch", "delete"], url_path="me",
            permission_classes=[IsAuthenticated])
    def me(self, request):
        """``GET/PATCH/DELETE /api/users/me/`` (TECHSPEC §4.2)."""
        if request.method == "GET":
            services.touch_last_seen(request.user.pk)
            return Response({"data": UserMeSerializer(request.user).data,
                             "meta": {}, "errors": []})

        if request.method == "DELETE":
            return self.delete_account(request)

        serializer = UserUpdateSerializer(instance=request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        username = data.pop("username", None)
        services.update_profile(request.user, data)

        if username and username != request.user.username:
            user = UserModel.objects.get(pk=request.user.pk)
            user.username = username
            user.save(update_fields=["username", "updated_at"])
        else:
            user = request.user
            user.refresh_from_db()

        return Response({"data": UserMeSerializer(user).data, "meta": {}, "errors": []})

    @action(detail=False, methods=["post"], url_path="me/password",
            permission_classes=[IsAuthenticated])
    def change_password(self, request):
        """``POST /api/users/me/password/`` (TECHSPEC §4.2)."""
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.change_password(request.user, **serializer.validated_data)
        except services.ServiceError as exc:
            return Response(
                {"data": None, "meta": None,
                 "errors": [{"code": exc.code, "field": exc.field, "message": exc.message}]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"data": {"detail": "Пароль обновлён"}, "meta": {}, "errors": []})

    def delete_account(self, request):
        """``DELETE /api/users/me/`` — soft-delete + анонимизация (TECHSPEC §4.2)."""
        serializer = AccountDeleteSerializer(data=request.data or {},
                                             context={"request": request})
        serializer.is_valid(raise_exception=True)

        # Содержимое остаётся, но обезличивается автор
        from apps.posts.models import Post
        from apps.threads.models import Thread

        user = request.user
        Thread.objects.filter(author=user).update(author=None)
        Post.objects.filter(author=user).update(author=None)
        user.soft_delete()

        logger.info("account_deleted", user_id=user.pk, ip=client_ip(request))

        from shared.authentication import clear_auth_cookies

        response = Response({"data": {"detail": "Аккаунт удалён"},
                             "meta": {}, "errors": []})
        clear_auth_cookies(response)
        return response


class UserStatsView(APIView):
    """Сводная статистика сообщества для главной страницы (TECHSPEC §1.2)."""

    permission_classes = [AllowAny]

    def get(self, request):
        from apps.forums.models import Forum
        from apps.posts.models import Post
        from apps.threads.models import Thread

        users_count = UserModel.objects.filter(is_deleted=False).count()
        stats = {
            "users": users_count,
            "users_new_7d": UserModel.objects.filter(
                is_deleted=False,
                date_joined__gte=timezone.now() - timedelta(days=7),
            ).count(),
            "threads": Thread.objects.filter(is_deleted=False).count(),
            "posts": Post.objects.filter(is_deleted=False).count(),
            "forums": Forum.objects.filter(parent__isnull=True).count(),
            "online": UserProfile.objects.filter(
                last_seen_at__gte=timezone.now() - timedelta(minutes=5)
            ).count(),
        }
        return Response({"data": stats, "meta": {}, "errors": []})
