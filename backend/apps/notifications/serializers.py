"""Сериализаторы уведомлений (TECHSPEC §11.8)."""

from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    """Уведомление с готовыми для UI полями (TECHSPEC §4.9)."""

    actor_username = serializers.CharField(source="actor", read_only=True)
    thread_slug = serializers.CharField(read_only=True)
    thread_title = serializers.SerializerMethodField()
    post_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Notification
        fields = ["id", "kind", "is_read", "created_at", "actor_username",
                  "thread_slug", "thread_title", "post_id"]
        read_only_fields = fields

    def get_thread_title(self, obj) -> str:
        return obj.payload.get("thread_title") or ""
