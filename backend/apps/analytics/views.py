"""Views аналитики: heatmap профиля и статистика (TECHSPEC §10.2)."""

from datetime import timedelta

from django.db.models import Avg, Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from shared.permissions import IsModerator

from .models import EventLog


class EventIngestSerializer(serializers.Serializer):
    """Событие от клиента (TECHSPEC §10.2)."""

    event_type = serializers.ChoiceField(choices=EventLog.Type.choices)
    payload = serializers.DictField(required=False, default=dict)
    at = serializers.DateTimeField(required=False)


class EventIngestView(APIView):
    """``POST /api/analytics/events/`` — приём клиентских событий (TECHSPEC §10.2)."""

    permission_classes = [AllowAny]
    throttle_scope = "events"

    def post(self, request):
        serializer = EventIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        EventLog.track(
            event_type=data["event_type"],
            user=request.user if request.user.is_authenticated else None,
            request=request,
            **data.get("payload", {}),
        )
        return Response({"data": {"accepted": True}, "meta": {}, "errors": []},
                        status=status.HTTP_202_ACCEPTED)


class ProfileHeatmapView(APIView):
    """``GET /api/analytics/heatmap/`` — активность пользователя по дням (TECHSPEC §4.2)."""

    permission_classes = [AllowAny]

    def get(self, request):
        from apps.accounts.models import User

        username = request.query_params.get("username")
        try:
            days = int(request.query_params.get("days", 365) or 365)
        except (TypeError, ValueError):
            days = 365
        days = max(1, min(days, 1095))

        queryset = EventLog.objects.all()
        if username:
            user = User.objects.filter(username=username).first()
            if user is None:
                return Response({"data": [], "meta": {}, "errors": []})
            queryset = queryset.filter(user=user)
        elif request.user.is_authenticated:
            queryset = queryset.filter(user=request.user)
        else:
            return Response({"data": [], "meta": {}, "errors": []})

        since = timezone.now() - timedelta(days=days)
        rows = (
            queryset.filter(created_at__gte=since)
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(count=Count("id"))
            .order_by("day")
        )
        return Response({
            "data": [{"date": row["day"], "count": row["count"]} for row in rows],
            "meta": {"days": days, "username": username or ""},
            "errors": [],
        })


class UserStatsView(APIView):
    """``GET /api/analytics/users/:id/stats/`` — публичная статистика (TECHSPEC §4.2)."""

    permission_classes = [AllowAny]

    def get(self, request, pk=None):
        from apps.accounts.models import User

        user = User.objects.filter(pk=pk).first()
        if user is None:
            return Response({"data": None, "meta": None,
                             "errors": [{"code": "not_found", "field": None,
                                         "message": "Пользователь не найден"}]},
                            status=status.HTTP_404_NOT_FOUND)

        profile = user.userprofile
        data = {
            "user_id": user.pk,
            "threads_count": profile.threads_count,
            "posts_count": profile.posts_count,
            "reactions_received": profile.reactions_received,
            "reputation": profile.reputation,
            "rank": profile.rank,
            "last_seen_at": profile.last_seen_at,
            "created_at": user.date_joined,
        }
        return Response({"data": data, "meta": {}, "errors": []})


class AdminStatsView(APIView):
    """``GET /api/analytics/stats/`` — сводка для модераторов (TECHSPEC §10.2)."""

    def get_permissions(self):
        return [IsModerator()]

    def get(self, request):
        from apps.posts.models import Post
        from apps.reactions.models import Reaction
        from apps.threads.models import Thread

        since = timezone.now() - timedelta(days=30)
        totals = {
            "users": EventLog.objects.filter(event_type=EventLog.Type.REGISTER).count(),
            "events_30d": EventLog.objects.filter(created_at__gte=since).count(),
            "threads": Thread.objects.filter(is_deleted=False).count(),
            "posts": Post.objects.filter(is_deleted=False).count(),
            "reactions": Reaction.objects.count(),
            "avg_reputation": _avg_reputation(),
        }
        by_type = list(
            EventLog.objects.filter(created_at__gte=since)
            .values("event_type")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        return Response({"data": {**totals, "events_by_type": by_type},
                         "meta": {"period_days": 30}, "errors": []})


def _avg_reputation() -> float:
    from apps.accounts.models import UserProfile

    value = UserProfile.objects.aggregate(avg=Avg("reputation"))["avg"]
    return round(value or 0.0, 2)
