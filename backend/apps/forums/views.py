"""Views разделов (TECHSPEC §11.4)."""

from django.db.models import Prefetch
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response

from shared.permissions import IsModerator

from .models import Forum
from .serializers import ForumSerializer, ForumWriteSerializer


class ForumViewSet(viewsets.ModelViewSet):
    """``/api/forums/`` — список, детали, темы раздела (TECHSPEC §4.3)."""

    serializer_class = ForumSerializer
    lookup_field = "slug"
    permission_classes = [AllowAny]
    ordering_fields = ["order", "name", "created_at"]
    ordering = ["order", "name"]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAdminUser()]
        return [AllowAny()]

    def get_queryset(self):
        qs = (
            Forum.objects.with_counts()
            .prefetch_related(
                Prefetch(
                    "children",
                    queryset=Forum.objects.with_counts().order_by("order", "name"),
                )
            )
            .order_by("order", "name")
        )
        if self.action == "list":
            return qs.filter(parent__isnull=True)
        return qs

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return ForumWriteSerializer
        return ForumSerializer

    def list(self, request, *args, **kwargs):
        """Корневые разделы с подразделами и статистикой."""
        queryset = self.filter_queryset(self.get_queryset())
        serializer = ForumSerializer(queryset, many=True, context={"request": request})
        return Response({"data": serializer.data,
                         "meta": {"count": queryset.count()}, "errors": []})

    @action(detail=True, methods=["get"])
    def threads(self, request, slug=None):
        """``GET /api/forums/:slug/threads/`` — темы раздела (TECHSPEC §11.4)."""
        from apps.threads.filters import ThreadFilter
        from apps.threads.models import Thread
        from apps.threads.serializers import ThreadListSerializer

        forum = self.get_object()
        queryset = (
            Thread.objects.filter(forum=forum, is_deleted=False)
            .select_related("forum", "author")
            .prefetch_related("tags")
        )
        queryset = ThreadFilter(request.query_params, queryset=queryset,
                                forum=forum).qs
        page = self.paginate_queryset(queryset)
        serializer = ThreadListSerializer(page or [], many=True, context={"request": request})
        return self.get_paginated_response(serializer.data)

    @action(detail=True, methods=["get"], permission_classes=[IsModerator])
    def stats(self, request, slug=None):
        """Статистика раздела для модератора (TECHSPEC §4.3)."""
        forum = self.get_object()
        from apps.threads.models import Thread

        stats = {
            "threads_total": Thread.objects.filter(forum=forum, is_deleted=False).count(),
            "threads_pinned": Thread.objects.filter(forum=forum, is_pinned=True).count(),
            "threads_locked": Thread.objects.filter(forum=forum, is_locked=True).count(),
            "threads_deleted": Thread.objects.filter(forum=forum, is_deleted=True).count(),
            "last_activity_at": forum.threads.order_by("-last_activity_at")
            .values_list("last_activity_at", flat=True).first(),
        }
        return Response({"data": stats, "meta": {}, "errors": []})
