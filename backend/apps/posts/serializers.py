"""Сериализаторы постов (TECHSPEC §11.6)."""

from django.conf import settings
from rest_framework import serializers

from apps.reactions.serializers import ReactionCountSerializer

from .models import Attachment, Post


class AttachmentSerializer(serializers.ModelSerializer):
    """Вложение поста (TECHSPEC §4.5)."""

    url = serializers.SerializerMethodField()
    is_image = serializers.BooleanField(read_only=True)
    human_size = serializers.CharField(read_only=True)

    class Meta:
        model = Attachment
        fields = ["id", "filename", "content_type", "size", "human_size", "is_image", "url"]
        read_only_fields = fields

    def get_url(self, obj) -> str:
        try:
            return obj.file.url
        except ValueError:  # pragma: no cover
            return ""


class QuoteBlockSerializer(serializers.Serializer):
    """Свёрнутая цитата (TECHSPEC §4.5)."""

    post_id = serializers.IntegerField()
    author_username = serializers.CharField()
    body_html = serializers.CharField()
    created_at = serializers.DateTimeField()


class PostAuthorSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    avatar = serializers.SerializerMethodField()
    reputation = serializers.IntegerField(read_only=True, default=0)
    rank = serializers.CharField(read_only=True)

    def get_avatar(self, obj):
        if obj is None:
            return None
        return obj.avatar_url


class PostSerializer(serializers.ModelSerializer):
    """Пост в треде (TECHSPEC §11.6)."""

    author = PostAuthorSerializer(read_only=True, allow_null=True)
    body = serializers.CharField(read_only=True)
    body_html = serializers.CharField(read_only=True)
    attachments = AttachmentSerializer(many=True, read_only=True)
    reactions = ReactionCountSerializer(source="*", read_only=True)
    quote = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    excerpt = serializers.SerializerMethodField()
    reply_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Post
        fields = ["id", "thread_id", "author", "parent_id", "body", "body_html",
                  "attachments", "reactions", "quote", "is_edited", "edited_at",
                  "is_deleted", "is_first_in_thread", "reactions_count", "reply_count",
                  "can_edit", "can_delete", "excerpt", "created_at", "updated_at"]
        read_only_fields = fields

    def get_quote(self, obj):
        """Цитата отображается свёрнутой (TECHSPEC §4.5)."""
        parent = obj.parent
        if parent is None:
            return None
        return QuoteBlockSerializer({
            "post_id": parent.pk,
            "author_username": parent.author_display,
            "body_html": parent.body_html[:600],
            "created_at": parent.created_at,
        }).data

    def get_can_edit(self, obj) -> bool:
        request = self.context.get("request")
        return obj.can_edit(getattr(request, "user", None))

    def get_can_delete(self, obj) -> bool:
        request = self.context.get("request")
        return obj.can_delete(getattr(request, "user", None))

    def get_excerpt(self, obj) -> str:
        from shared.markdown import extract_text_preview

        return extract_text_preview(obj.body, 180)


class PostCreateSerializer(serializers.Serializer):
    """Создание поста в теме (TECHSPEC §11.6)."""

    body = serializers.CharField()
    parent = serializers.IntegerField(required=False, allow_null=True)

    def validate_body(self, value):
        max_length = getattr(settings, "BODY_MAX_LENGTH", 50_000)
        if not value.strip():
            raise serializers.ValidationError("Пост не может быть пустым")
        if len(value) > max_length:
            raise serializers.ValidationError(f"Текст длиннее {max_length} символов")
        return value

    def validate_parent(self, value):
        if value is None:
            return None
        thread = self.context["thread"]
        if not Post.objects.filter(pk=value, thread=thread).exists():
            raise serializers.ValidationError("Цитируемый пост не найден в этой теме")
        # Вложенная цитата ограничена 3 уровнями (TECHSPEC §4.5)
        depth = 1
        parent = Post.objects.filter(pk=value).first()
        seen = set()
        while parent is not None and parent.parent_id and parent.pk not in seen:
            seen.add(parent.pk)
            depth += 1
            parent = parent.parent
            if depth > 3:
                raise serializers.ValidationError("Вложенность цитат ограничена 3 уровнями")
        return value


class PostUpdateSerializer(serializers.Serializer):
    """Редактирование поста (TECHSPEC §4.5)."""

    body = serializers.CharField()

    def validate_body(self, value):
        max_length = getattr(settings, "BODY_MAX_LENGTH", 50_000)
        if not value.strip():
            raise serializers.ValidationError("Пост не может быть пустым")
        if len(value) > max_length:
            raise serializers.ValidationError(f"Текст длиннее {max_length} символов")
        return value


class PostPreviewSerializer(serializers.Serializer):
    body = serializers.CharField(required=False, allow_blank=True)
