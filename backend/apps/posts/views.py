"""Views постов (TECHSPEC §11.6)."""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from shared.logging import get_logger
from shared.markdown import render_markdown
from shared.permissions import IsAuthorOrReadOnly
from shared.validators import validate_upload

from .models import Post
from .serializers import PostSerializer, PostUpdateSerializer
from .services import ServiceError, soft_delete_post, update_post

logger = get_logger("forumos.posts")


class PostViewSet(viewsets.ModelViewSet):
    """``/api/posts/`` — чтение, редактирование, удаление (TECHSPEC §4.5)."""

    queryset = Post.objects.with_related().prefetch_related("attachments")
    serializer_class = PostSerializer
    permission_classes = [AllowAny, IsAuthorOrReadOnly]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]
    filterset_fields = ["is_edited", "thread"]

    #: Действия, доступные анонимному посетителю (TECHSPEC §4.5).
    PUBLIC_ACTIONS = ("list", "retrieve", "reactions", "preview")

    def get_permissions(self):
        if self.action in self.PUBLIC_ACTIONS:
            return [AllowAny()]
        if self.action in ("update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsAuthorOrReadOnly()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.visible_to(self.request.user)

    def get_serializer_class(self):
        if self.action in ("update", "partial_update"):
            return PostUpdateSerializer
        return PostSerializer

    def update(self, request, *args, **kwargs):
        """``PATCH /api/posts/:id/`` (TECHSPEC §4.5)."""
        post = self.get_object()
        serializer = PostUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            update_post(post, request.user, body=serializer.validated_data["body"])
        except ServiceError as exc:
            return _error(exc)

        post.refresh_from_db()
        return Response({"data": PostSerializer(post, context={"request": request}).data,
                         "meta": {}, "errors": []})

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        """``DELETE /api/posts/:id/`` — soft-delete (TECHSPEC §4.5)."""
        post = self.get_object()
        try:
            soft_delete_post(post, request.user)
        except ServiceError as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="react",
            permission_classes=[IsAuthenticated])
    def react(self, request, pk=None):
        """``POST /api/posts/:id/react/`` — toggle реакции (TECHSPEC §11.6)."""
        from apps.reactions.serializers import ReactionToggleSerializer
        from apps.reactions.services import ServiceError as ReactionError
        from apps.reactions.services import toggle_reaction

        post = self.get_object()
        serializer = ReactionToggleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = toggle_reaction(post, request.user,
                                     serializer.validated_data["reaction"])
        except ReactionError as exc:
            return _error(exc)

        from ws.broadcast import broadcast_reaction

        broadcast_reaction(post, result, actor_id=request.user.pk)
        return Response({"data": result, "meta": {}, "errors": []})

    @action(detail=True, methods=["get"], url_path="reactions")
    def reactions(self, request, pk=None):
        """``GET /api/posts/:id/reactions/`` — список реакций (TECHSPEC §11.6)."""
        post = self.get_object()
        from apps.reactions.serializers import PostReactionUserSerializer

        reactions = post.reactions.select_related("user", "reaction").order_by("created_at")
        data = PostReactionUserSerializer(reactions, many=True,
                                          context={"request": request}).data
        return Response({"data": data, "meta": {"count": len(data)}, "errors": []})

    @action(detail=False, methods=["post"], url_path="preview")
    def preview(self, request):
        """Предпросмотр markdown."""
        return Response({"data": {"body_html": render_markdown(request.data.get("body", ""))},
                         "meta": {}, "errors": []})

    @action(detail=True, methods=["post"], url_path="upload",
            permission_classes=[IsAuthenticated])
    def upload(self, request, pk=None):
        """Загрузка вложения к посту (TECHSPEC §4.5, §15.7)."""
        from django.conf import settings

        post = self.get_object()
        if post.author_id != request.user.pk and not post.can_edit(request.user):
            return _error(ServiceError("Нет прав на редактирование поста", code="forbidden"))

        uploaded = request.FILES.get("file")
        if uploaded is None:
            return Response({"data": None, "meta": None,
                             "errors": [{"code": "required", "field": "file",
                                         "message": "Файл не передан"}]},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            validate_upload(uploaded, settings.ATTACHMENT_MAX_BYTES,
                            settings.ATTACHMENT_ALLOWED_TYPES)
        except Exception as exc:
            return Response({"data": None, "meta": None,
                             "errors": [{"code": "invalid_file", "field": "file",
                                         "message": getattr(exc, "messages", [str(exc)])[0]}]},
                            status=status.HTTP_400_BAD_REQUEST)

        from .serializers import AttachmentSerializer

        attachment = post.attachments.create(
            file=uploaded,
            filename=uploaded.name,
            content_type=uploaded.content_type or "application/octet-stream",
            size=uploaded.size,
        )
        return Response({"data": AttachmentSerializer(attachment).data,
                         "meta": {}, "errors": []}, status=status.HTTP_201_CREATED)


def _error(exc: ServiceError):
    http_status = (status.HTTP_403_FORBIDDEN if exc.code == "forbidden"
                   else status.HTTP_400_BAD_REQUEST)
    return Response({"data": None, "meta": None,
                     "errors": [{"code": exc.code, "field": exc.field,
                                 "message": exc.message}]}, status=http_status)
