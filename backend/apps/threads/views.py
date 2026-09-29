"""Views тем (TECHSPEC §11.5)."""

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.forums.models import Forum
from shared.logging import get_logger
from shared.permissions import CanCreateThread, IsAuthorOrReadOnly

from .models import Thread, ThreadDraft
from .serializers import (
    ThreadDetailSerializer,
    ThreadDraftSerializer,
    ThreadListSerializer,
    ThreadPreviewSerializer,
    ThreadWriteSerializer,
)
from .services import (
    ServiceError,
    move_thread,
    register_view,
    set_locked,
    set_pinned,
    soft_delete_thread,
    toggle_subscription,
    update_thread,
)

logger = get_logger("forumos.threads")


class ThreadViewSet(viewsets.ModelViewSet):
    """``/api/threads/`` — CRUD, модерация, подписки (TECHSPEC §11.5)."""

    lookup_field = "slug"
    ordering_fields = ["created_at", "last_activity_at", "reactions_count", "views_count",
                       "posts_count", "title"]
    ordering = ["-last_activity_at"]

    def get_permissions(self):
        if self.action in ("create",):
            return [IsAuthenticated(), CanCreateThread()]
        if self.action in ("update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsAuthorOrReadOnly()]
        if self.action in ("pin", "unpin", "lock", "unlock", "move"):
            return [IsAuthenticated()]
        return [AllowAny()]

    def get_queryset(self):
        qs = Thread.objects.filter(is_draft=False).with_related()
        user = self.request.user
        if user.is_authenticated and not (user.is_staff or user.is_superuser):
            qs = qs.filter(
                # Удалённые темы видит автор и модератор (TECHSPEC §4.4)
                models_q_visible(user)
            )
        return qs

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return ThreadWriteSerializer
        if self.action == "preview":
            return ThreadPreviewSerializer
        if self.action in ("retrieve",):
            return ThreadDetailSerializer
        return ThreadListSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    # ── Список и создание ────────────────────────────────────────
    def list(self, request, *args, **kwargs):
        """``GET /api/threads/`` — фильтры и сортировки (TECHSPEC §4.3)."""
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page or [], many=True)
        return self.get_paginated_response(serializer.data)

    def create(self, request, *args, **kwargs):
        """``POST /api/threads/`` (TECHSPEC §4.4)."""
        from .services import create_thread, notify_mentions

        serializer = ThreadWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        thread = create_thread(
            author=request.user,
            forum=data["forum"],
            title=data["title"],
            body=data["body"],
            tags=data.get("tags") or [],
            is_draft=data.get("is_draft", False),
        )
        notify_mentions(thread, author=request.user, request=request)

        detail = ThreadDetailSerializer(thread, context={"request": request})
        return Response({"data": detail.data, "meta": {}, "errors": []},
                        status=status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        """``GET /api/threads/:slug/`` + счётчик просмотров (TECHSPEC §4.4)."""
        thread = self.get_object()
        register_view(thread, request.user, request)
        serializer = ThreadDetailSerializer(thread, context={"request": request})
        return Response({"data": serializer.data, "meta": {}, "errors": []})

    def partial_update(self, request, *args, **kwargs):
        thread = self.get_object()
        serializer = ThreadWriteSerializer(thread, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            update_thread(thread, request.user,
                          title=serializer.validated_data.get("title"),
                          body=serializer.validated_data.get("body"))
        except ServiceError as exc:
            return _error(exc)
        thread.refresh_from_db()
        return Response({"data": ThreadDetailSerializer(thread, context={"request": request}).data,
                         "meta": {}, "errors": []})

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        """``DELETE /api/threads/:slug/`` — soft-delete (TECHSPEC §4.4)."""
        thread = self.get_object()
        hard = str(request.query_params.get("hard", "")).lower() in ("1", "true")
        try:
            soft_delete_thread(thread, request.user, hard=hard)
        except ServiceError as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ── Модерация (TECHSPEC §4.4) ────────────────────────────────
    @action(detail=True, methods=["post"], url_path="pin")
    def pin(self, request, slug=None):
        thread = self.get_object()
        try:
            set_pinned(thread, request.user, True)
        except ServiceError as exc:
            return _error(exc)
        return Response({"data": {"slug": thread.slug, "is_pinned": True},
                         "meta": {}, "errors": []})

    @action(detail=True, methods=["post"], url_path="unpin")
    def unpin(self, request, slug=None):
        thread = self.get_object()
        try:
            set_pinned(thread, request.user, False)
        except ServiceError as exc:
            return _error(exc)
        return Response({"data": {"slug": thread.slug, "is_pinned": False},
                         "meta": {}, "errors": []})

    @action(detail=True, methods=["post"], url_path="lock")
    def lock(self, request, slug=None):
        thread = self.get_object()
        try:
            set_locked(thread, request.user, True)
        except ServiceError as exc:
            return _error(exc)
        return Response({"data": {"slug": thread.slug, "is_locked": True},
                         "meta": {}, "errors": []})

    @action(detail=True, methods=["post"], url_path="unlock")
    def unlock(self, request, slug=None):
        thread = self.get_object()
        try:
            set_locked(thread, request.user, False)
        except ServiceError as exc:
            return _error(exc)
        return Response({"data": {"slug": thread.slug, "is_locked": False},
                         "meta": {}, "errors": []})

    @action(detail=True, methods=["post"], url_path="move")
    def move(self, request, slug=None):
        """Перенос темы в другой раздел."""
        from .serializers import TagWriteSerializer  # noqa: F401  (единый стиль ответов)

        thread = self.get_object()
        target = request.data.get("forum")
        if not target:
            return Response({"data": None, "meta": None,
                             "errors": [{"code": "required", "field": "forum",
                                         "message": "Укажите раздел"}]},
                            status=status.HTTP_400_BAD_REQUEST)
        forum = Forum.objects.filter(slug=target).first()
        if forum is None:
            return Response({"data": None, "meta": None,
                             "errors": [{"code": "not_found", "field": "forum",
                                         "message": "Раздел не найден"}]},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            move_thread(thread, request.user, forum)
        except ServiceError as exc:
            return _error(exc)
        return Response({"data": {"slug": thread.slug, "forum": forum.slug},
                         "meta": {}, "errors": []})

    # ── Подписки (TECHSPEC §4.4) ─────────────────────────────────
    @action(detail=True, methods=["post", "delete"], url_path="subscribe",
            permission_classes=[IsAuthenticated])
    def subscribe(self, request, slug=None):
        thread = self.get_object()
        result = toggle_subscription(thread, request.user)
        logger.info("thread_subscription", thread_id=thread.pk, user_id=request.user.pk,
                    **result)
        return Response({"data": result, "meta": {}, "errors": []})

    # ── Черновики (TECHSPEC §4.4) ────────────────────────────────
    @action(detail=False, methods=["get", "put", "delete"], url_path="draft",
            permission_classes=[IsAuthenticated])
    def draft(self, request, slug=None):
        """Автосохранение черновика раз в 10 секунд."""
        instance, _ = ThreadDraft.objects.get_or_create(user=request.user)
        if request.method == "GET":
            return Response({"data": ThreadDraftSerializer(instance).data,
                             "meta": {}, "errors": []})
        if request.method == "DELETE":
            instance.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = ThreadDraftSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"data": serializer.data, "meta": {}, "errors": []})

    @action(detail=False, methods=["post"], url_path="preview",
            permission_classes=[AllowAny])
    def preview(self, request):
        """Предпросмотр markdown перед публикацией."""
        serializer = ThreadPreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from shared.markdown import render_markdown

        return Response({"data": {"body_html": render_markdown(request.data.get("body", ""))},
                         "meta": {}, "errors": []})


def models_q_visible(user):
    """Удалённые темы видит автор; модераторы видят всё (TECHSPEC §4.4)."""
    from django.db.models import Q

    return Q(is_deleted=False) | Q(author=user)


def _error(exc: ServiceError):
    http_status = (status.HTTP_403_FORBIDDEN if exc.code == "forbidden"
                   else status.HTTP_400_BAD_REQUEST)
    return Response({"data": None, "meta": None,
                     "errors": [{"code": exc.code, "field": exc.field,
                                 "message": exc.message}]}, status=http_status)


class ThreadPostsViewSet(viewsets.ViewSet):
    """``/api/threads/:slug/posts/`` — посты темы (TECHSPEC §11.6)."""

    def list(self, request, slug=None):
        from apps.posts.serializers import PostSerializer
        from apps.posts.services import list_thread_posts

        thread = get_object_or_404(Thread, slug=slug)
        queryset = list_thread_posts(thread, request.user)
        paginator = self.paginator
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = PostSerializer(page or [], many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    def create(self, request, slug=None):
        from apps.posts.serializers import PostCreateSerializer
        from apps.posts.services import ServiceError as PostServiceError
        from apps.posts.services import create_post

        thread = get_object_or_404(Thread, slug=slug)
        serializer = PostCreateSerializer(data=request.data, context={"thread": thread})
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        parent = payload.pop("parent", None)
        try:
            post = create_post(thread=thread, author=request.user,
                               parent_id=parent, **payload)
        except PostServiceError as exc:
            return Response({"data": None, "meta": None,
                             "errors": [{"code": exc.code, "field": exc.field,
                                         "message": exc.message}]},
                            status=status.HTTP_403_FORBIDDEN
                            if exc.code == "forbidden"
                            else status.HTTP_400_BAD_REQUEST)

        from apps.posts.serializers import PostSerializer

        payload = PostSerializer(post, context={"request": request}).data
        # Real-time доставка всем, кто в треде (TECHSPEC §6.3, §12.4)
        from ws.broadcast import broadcast_post_created

        broadcast_post_created(thread, post, actor_id=request.user.pk)
        return Response({"data": payload, "meta": {}, "errors": []},
                        status=status.HTTP_201_CREATED)

    @property
    def paginator(self):
        from shared.pagination import CursorPagination

        if not hasattr(self, "_paginator"):
            self._paginator = CursorPagination()
        return self._paginator
