"""Views уведомлений (TECHSPEC §11.8)."""

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Notification
from .serializers import NotificationSerializer
from .services import mark_all_read, mark_read, unread_count


class NotificationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """``/api/notifications/`` — список, прочитано, удаление (TECHSPEC §4.9)."""

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    ordering = ["-created_at"]
    ordering_fields = ["created_at", "is_read"]
    filterset_fields = ["is_read", "kind"]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @action(detail=True, methods=["post"], url_path="read")
    def read(self, request, pk=None):
        """``POST /api/notifications/:id/read/``."""
        notification = self.get_object()
        mark_read(notification)
        return Response({"data": NotificationSerializer(notification).data,
                         "meta": {}, "errors": []})

    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        """``POST /api/notifications/read-all/``."""
        updated = mark_all_read(request.user.pk)
        return Response({"data": {"updated": updated}, "meta": {}, "errors": []})

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread(self, request):
        """``GET /api/notifications/unread-count/``."""
        return Response({"data": {"count": unread_count(request.user.pk)},
                         "meta": {}, "errors": []})

    def destroy(self, request, *args, **kwargs):
        self.get_object().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
