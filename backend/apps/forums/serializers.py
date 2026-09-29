"""Сериализаторы разделов (TECHSPEC §11.4)."""

from rest_framework import serializers

from .models import Forum


class ForumSerializer(serializers.ModelSerializer):
    """Раздел с вложенными подразделами и статистикой (TECHSPEC §1.2)."""

    children = serializers.SerializerMethodField()
    thread_count = serializers.IntegerField(read_only=True)
    post_count = serializers.SerializerMethodField()
    last_activity = serializers.SerializerMethodField()
    can_moderate = serializers.SerializerMethodField()

    class Meta:
        model = Forum
        fields = ["id", "name", "slug", "description", "accent", "icon", "order",
                  "parent", "children", "thread_count", "post_count",
                  "last_activity", "can_moderate", "created_at"]
        read_only_fields = ["id", "slug", "order", "created_at", "thread_count",
                            "post_count", "last_activity", "can_moderate", "children"]

    def get_children(self, obj):
        children = list(obj.children.all()) if hasattr(obj, "children") else []
        if not children:
            return []
        return ForumSerializer(children, many=True, context=self.context).data

    def get_post_count(self, obj) -> int:
        return obj.post_count

    def get_last_activity(self, obj):
        thread = obj.last_activity
        if thread is None:
            return None
        return {
            "thread_id": thread.id,
            "slug": thread.slug,
            "title": thread.title,
            "author": thread.author.username if thread.author else "удалён",
            "last_activity_at": thread.last_activity_at,
        }

    def get_can_moderate(self, obj) -> bool:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return obj.can_moderate(user)


class ForumWriteSerializer(serializers.ModelSerializer):
    """Создание/обновление раздела — только для админов (Django admin + API)."""

    class Meta:
        model = Forum
        fields = ["name", "slug", "description", "parent", "accent", "icon", "order",
                  "moderator", "is_closed"]

    def validate_parent(self, value):
        # В MVP — один уровень вложенности (TECHSPEC §4.3)
        if value is not None and value.parent_id is not None:
            raise serializers.ValidationError("Вложенность ограничена одним уровнем")
        return value

    def validate_accent(self, value):
        from shared.validators import validate_hex_color

        validate_hex_color(value)
        return value
