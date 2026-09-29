"""Сериализаторы модерации (TECHSPEC §11.9)."""

from rest_framework import serializers

from .models import AuditLog, Ban, Flag, FlagReason, TargetType


class FlagSerializer(serializers.ModelSerializer):
    """Жалоба в очереди модерации (TECHSPEC §4.10)."""

    reporter = serializers.SerializerMethodField()
    resolved_by = serializers.SerializerMethodField()
    target_preview = serializers.SerializerMethodField()

    class Meta:
        model = Flag
        fields = ["id", "reporter", "target_type", "target_id", "target_preview",
                  "reason", "comment", "status", "resolved_by", "resolved_at",
                  "moderator_comment", "created_at"]
        read_only_fields = ["id", "status", "resolved_by", "resolved_at",
                            "moderator_comment", "created_at", "reporter", "target_preview"]

    def get_reporter(self, obj) -> dict:
        return {"id": obj.reporter_id, "username": obj.reporter.username}

    def get_resolved_by(self, obj):
        if obj.resolved_by_id is None:
            return None
        return {"id": obj.resolved_by_id, "username": obj.resolved_by.username}

    def get_target_preview(self, obj) -> str | None:
        """Короткий текст цели жалобы для очереди."""
        from shared.markdown import extract_text_preview

        target = obj.target
        if target is None:
            return None
        body = getattr(target, "body", None) or getattr(target, "bio", "") or ""
        return extract_text_preview(body, 140)


class FlagCreateSerializer(serializers.Serializer):
    """Создание жалобы (TECHSPEC §4.10)."""

    target_type = serializers.ChoiceField(choices=TargetType.choices)
    target_id = serializers.IntegerField(min_value=1)
    reason = serializers.ChoiceField(choices=FlagReason.choices)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=1000)

    def validate(self, attrs):
        target = self._resolve_target(attrs["target_type"], attrs["target_id"])
        if target is None:
            raise serializers.ValidationError({"target_id": "Объект не найден"})
        return attrs

    @staticmethod
    def _resolve_target(target_type: str, target_id: int):
        from django.apps import apps as django_apps

        mapping = {
            TargetType.POST: ("posts", "Post"),
            TargetType.THREAD: ("threads", "Thread"),
            TargetType.USER: ("accounts", "User"),
        }
        entry = mapping.get(target_type)
        if entry is None:
            return None
        try:
            model = django_apps.get_model(*entry)
        except LookupError:  # pragma: no cover
            return None
        return model.objects.filter(pk=target_id).first()


class BanSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    issued_by = serializers.SerializerMethodField()
    is_effective = serializers.BooleanField(read_only=True)

    class Meta:
        model = Ban
        fields = ["id", "user", "issued_by", "reason", "duration", "expires_at",
                  "is_active", "is_effective", "lifted_at", "created_at"]
        read_only_fields = fields

    def get_user(self, obj) -> dict:
        return {"id": obj.user_id, "username": obj.user.username}

    def get_issued_by(self, obj):
        if obj.issued_by_id is None:
            return None
        return {"id": obj.issued_by_id, "username": obj.issued_by.username}


class AuditLogSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = ["id", "actor", "action", "target_type", "target_id", "payload", "created_at"]
        read_only_fields = fields

    def get_actor(self, obj) -> dict:
        return {"id": obj.actor_id, "username": obj.actor.username}
