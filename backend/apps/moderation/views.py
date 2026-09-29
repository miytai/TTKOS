"""Views модерации (TECHSPEC §11.9)."""

from django.contrib.auth import get_user_model
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from shared.permissions import IsModerator

from .models import AuditLog, Ban, Flag
from .serializers import (
    AuditLogSerializer,
    BanSerializer,
    FlagCreateSerializer,
    FlagSerializer,
)
from .services import (
    ModerationError,
    ban_user,
    create_flag,
    delete_thread,
    hide_post,
    reject_flag,
    resolve_flag,
    unban_user,
    warn_user,
)

UserModel = get_user_model()


def _error(exc: ModerationError):
    return Response({"data": None, "meta": None,
                     "errors": [{"code": exc.code, "field": None,
                                 "message": exc.message}]},
                    status=status.HTTP_400_BAD_REQUEST)


class FlagViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                  mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """``/api/moderation/flags/`` — очередь жалоб (TECHSPEC §11.9)."""

    serializer_class = FlagSerializer
    permission_classes = [IsAuthenticated, IsModerator]
    filterset_fields = ["status", "reason", "target_type"]
    ordering = ["-created_at"]
    ordering_fields = ["created_at", "status"]

    def get_queryset(self):
        return Flag.objects.select_related("reporter", "resolved_by")

    def get_permissions(self):
        # Пожаловаться может любой авторизованный пользователь,
        # а очередь жалоб видят только модераторы (TECHSPEC §4.10).
        if self.action == "create":
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsModerator()]

    def create(self, request, *args, **kwargs):
        """Пожаловаться на контент или пользователя (TECHSPEC §4.10)."""
        serializer = FlagCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        flag = create_flag(
            reporter=request.user,
            target_type=data["target_type"],
            target_id=data["target_id"],
            reason=data["reason"],
            comment=data.get("comment", ""),
        )
        return Response({"data": FlagSerializer(flag).data, "meta": {}, "errors": []},
                        status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        """``POST /api/moderation/flags/:id/resolve/``."""
        flag = self.get_object()
        try:
            resolve_flag(flag, request.user, request.data.get("comment", ""))
        except ModerationError as exc:
            return _error(exc)
        return Response({"data": FlagSerializer(flag).data, "meta": {}, "errors": []})

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        """``POST /api/moderation/flags/:id/reject/``."""
        flag = self.get_object()
        try:
            reject_flag(flag, request.user, request.data.get("comment", ""))
        except ModerationError as exc:
            return _error(exc)
        return Response({"data": FlagSerializer(flag).data, "meta": {}, "errors": []})


class ModerationUserViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """``/api/moderation/users/`` — баны и предупреждения (TECHSPEC §11.9)."""

    serializer_class = BanSerializer
    permission_classes = [IsAuthenticated, IsModerator]

    def get_queryset(self):
        return Ban.objects.select_related("user", "issued_by").order_by("-created_at")

    def list(self, request, *args, **kwargs):
        from apps.accounts.serializers import UserSerializer

        queryset = UserModel.objects.filter(is_deleted=False).order_by("-date_joined")
        serializer = UserSerializer(queryset[:100], many=True)
        return Response({"data": serializer.data, "meta": {}, "errors": []})

    @action(detail=True, methods=["post"])
    def ban(self, request, pk=None):
        """``POST /api/moderation/users/:id/ban/``."""
        target = _get_user(pk)
        if target is None:
            return _not_found()
        try:
            ban = ban_user(
                target_user=target, moderator=request.user,
                duration=request.data.get("duration", "1d"),
                reason=request.data.get("reason", ""),
            )
        except ModerationError as exc:
            return _error(exc)
        return Response({"data": BanSerializer(ban).data, "meta": {}, "errors": []},
                        status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def unban(self, request, pk=None):
        """``POST /api/moderation/users/:id/unban/``."""
        target = _get_user(pk)
        if target is None:
            return _not_found()
        unban_user(target_user=target, moderator=request.user)
        return Response({"data": {"unbanned": True}, "meta": {}, "errors": []})

    @action(detail=True, methods=["post"])
    def warn(self, request, pk=None):
        target = _get_user(pk)
        if target is None:
            return _not_found()
        warn_user(target_user=target, moderator=request.user,
                  message=request.data.get("message", "")[:500])
        return Response({"data": {"warned": True}, "meta": {}, "errors": []})


class AuditLogViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                      viewsets.GenericViewSet):
    """``/api/moderation/audit-log/`` — журнал действий (TECHSPEC §11.9)."""

    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated, IsModerator]
    filterset_fields = ["action", "actor"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return AuditLog.objects.select_related("actor")


class ModerationContentView(viewsets.ViewSet):
    """``/api/moderation/posts/:id/hide/`` и ``threads/:id/hide/`` (TECHSPEC §11.9)."""

    permission_classes = [IsAuthenticated, IsModerator]

    @action(detail=True, methods=["post"], url_path="hide")
    def hide_post(self, request, pk=None):
        """``POST /api/moderation/posts/:id/hide/`` — скрыть пост."""
        from apps.posts.models import Post

        post = Post.objects.filter(pk=pk).first()
        if post is None:
            return _not_found()
        try:
            hide_post(post, request.user, request.data.get("reason", ""))
        except ModerationError as exc:
            return _error(exc)
        return Response({"data": {"hidden": True, "post_id": post.pk},
                         "meta": {}, "errors": []})

    @action(detail=True, methods=["post"], url_path="hide")
    def hide_thread(self, request, pk=None):
        """``POST /api/moderation/threads/:id/hide/`` — удалить тему."""
        from apps.threads.models import Thread

        thread = Thread.objects.filter(pk=pk).first()
        if thread is None:
            return _not_found()
        delete_thread(thread, request.user, request.data.get("reason", ""))
        return Response({"data": {"deleted": True, "thread_id": thread.pk},
                         "meta": {}, "errors": []})


def _get_user(pk):
    return UserModel.objects.filter(pk=pk).first()


def _not_found():
    return Response({"data": None, "meta": None,
                     "errors": [{"code": "not_found", "field": None,
                                 "message": "Объект не найден"}]},
                    status=status.HTTP_404_NOT_FOUND)
