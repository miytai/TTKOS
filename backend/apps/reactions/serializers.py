"""Сериализаторы реакций (TECHSPEC §4.5, §11.6)."""

from rest_framework import serializers

from .models import PostReaction, Reaction


class ReactionSerializer(serializers.ModelSerializer):
    """Справочник типов реакций."""

    class Meta:
        model = Reaction
        fields = ["code", "emoji", "karma_value", "order"]


class ReactionCountSerializer(serializers.Serializer):
    """Счётчики реакций поста + реакция текущего пользователя (TECHSPEC §11.6)."""

    counts = serializers.SerializerMethodField()
    total = serializers.IntegerField(read_only=True, source="reactions_count")
    mine = serializers.SerializerMethodField()

    def get_counts(self, obj) -> dict:
        cached = getattr(obj, "reaction_counts_cache", None)
        if cached is not None:
            return cached
        from django.db.models import Count

        rows = (
            obj.reactions.values("reaction__code")
            .annotate(count=Count("id"))
            .order_by()
        )
        return {row["reaction__code"]: row["count"] for row in rows}

    def get_mine(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return []
        codes = list(
            obj.reactions.filter(user=user).values_list("reaction__code", flat=True)
        )
        return codes


class ReactionToggleSerializer(serializers.Serializer):
    """Вход toggle-реакции: ``{"reaction": "like"}`` (TECHSPEC §11.6)."""

    reaction = serializers.CharField(max_length=16)

    def validate_reaction(self, value):
        code = value.strip().lower()
        if not Reaction.objects.filter(code=code).exists():
            raise serializers.ValidationError("Неизвестный тип реакции")
        return code


class PostReactionUserSerializer(serializers.ModelSerializer):
    """Реакция + пользователь (TECHSPEC §11.6)."""

    user = serializers.SerializerMethodField()
    reaction = serializers.CharField(source="reaction.code")
    emoji = serializers.CharField(source="reaction.emoji")

    class Meta:
        model = PostReaction
        fields = ["id", "user", "reaction", "emoji", "created_at"]

    def get_user(self, obj):
        user = obj.user
        return {
            "id": user.pk,
            "username": user.username,
            "avatar": user.avatar_url,
            "reputation": user.reputation,
        }
