"""Сериализаторы тем (TECHSPEC §11.5)."""

from django.conf import settings
from rest_framework import serializers

from apps.forums.models import Forum
from apps.forums.serializers import ForumSerializer
from shared.markdown import render_markdown
from shared.utils import extract_mentions

from .models import Tag, Thread, ThreadDraft


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "name", "slug", "usage_count"]
        read_only_fields = ["id", "slug", "usage_count"]


class TagWriteSerializer(serializers.Serializer):
    """Теги передаются как список строк или slug'ов (TECHSPEC §11.5)."""

    MAX_TAGS = 5
    MAX_LENGTH = 40

    def to_internal_value(self, data):
        if not isinstance(data, list):
            raise serializers.ValidationError("Ожидается список тегов")
        if len(data) > self.MAX_TAGS:
            raise serializers.ValidationError(f"Не более {self.MAX_TAGS} тегов")

        normalized = []
        for item in data:
            value = item.get("name") if isinstance(item, dict) else item
            if not isinstance(value, str):
                raise serializers.ValidationError("Тег должен быть строкой")
            value = value.strip().lower()
            if not value:
                continue
            if len(value) > self.MAX_LENGTH:
                raise serializers.ValidationError(f"Тег длиннее {self.MAX_LENGTH} символов")
            if value not in normalized:
                normalized.append(value)
        return normalized


class ThreadAuthorSerializer(serializers.Serializer):
    """Компактный автор в списках (TECHSPEC §1.2 — плотность информации)."""

    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    avatar = serializers.SerializerMethodField()
    reputation = serializers.IntegerField(read_only=True, default=0)

    def get_avatar(self, obj):
        if isinstance(obj, dict):  # pragma: no cover - dict-автор (удалённый)
            return obj.get("avatar")
        return obj.avatar_url


class ThreadListSerializer(serializers.ModelSerializer):
    """Компактное представление темы для лент (TECHSPEC §11.5)."""

    author = ThreadAuthorSerializer(read_only=True, allow_null=True)
    forum = ForumSerializer(read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    is_subscribed = serializers.SerializerMethodField()
    reading_time = serializers.IntegerField(read_only=True)

    class Meta:
        model = Thread
        fields = ["id", "slug", "title", "author", "forum", "tags", "is_pinned", "is_locked",
                  "views_count", "posts_count", "reactions_count", "last_activity_at",
                  "created_at", "is_subscribed", "reading_time"]

    def get_is_subscribed(self, obj) -> bool:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        return obj.subscriptions.filter(user=user).exists()


class ThreadDetailSerializer(ThreadListSerializer):
    """Полное представление темы для страницы (TECHSPEC §4.4)."""

    body = serializers.CharField(read_only=True)
    body_html = serializers.CharField(read_only=True)
    breadcrumbs = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_moderate = serializers.SerializerMethodField()
    excerpt = serializers.SerializerMethodField()

    class Meta(ThreadListSerializer.Meta):
        fields = [
            *ThreadListSerializer.Meta.fields,
            "body", "body_html", "breadcrumbs", "can_edit", "can_moderate", "excerpt",
            "updated_at", "is_deleted",
        ]

    def get_breadcrumbs(self, obj):
        crumbs = [{"name": "Главная", "url": "/"}]
        forum = obj.forum
        if forum.parent_id:
            crumbs.append({"name": forum.parent.name, "url": f"/f/{forum.parent.slug}"})
        crumbs.append({"name": forum.name, "url": f"/f/{forum.slug}"})
        crumbs.append({"name": obj.title, "url": f"/t/{obj.slug}"})
        return crumbs

    def get_can_edit(self, obj) -> bool:
        request = self.context.get("request")
        return obj.can_edit(getattr(request, "user", None))

    def get_can_moderate(self, obj) -> bool:
        request = self.context.get("request")
        return obj.can_moderate(getattr(request, "user", None))

    def get_excerpt(self, obj) -> str:
        from shared.markdown import extract_text_preview

        return extract_text_preview(obj.body, 200)


class ThreadWriteSerializer(serializers.ModelSerializer):
    """Создание и обновление темы (TECHSPEC §4.4)."""

    forum = serializers.SlugRelatedField(slug_field="slug", queryset=Forum.objects.all())
    tags = TagWriteSerializer(required=False)
    mentions = serializers.SerializerMethodField()

    class Meta:
        model = Thread
        fields = ["forum", "title", "body", "tags", "is_draft", "mentions"]
        extra_kwargs = {"is_draft": {"required": False}}

    def validate_title(self, value):
        value = value.strip()
        if not (10 <= len(value) <= 200):
            raise serializers.ValidationError("Заголовок: от 10 до 200 символов")
        return value

    def validate_body(self, value):
        max_length = getattr(settings, "BODY_MAX_LENGTH", 50_000)
        if not value.strip():
            raise serializers.ValidationError("Тело темы не может быть пустым")
        if len(value) > max_length:
            raise serializers.ValidationError(f"Тело длиннее {max_length} символов")
        return value

    def get_mentions(self, obj) -> list[str]:
        return extract_mentions(obj.body or "")

    def create(self, validated_data):
        tags = validated_data.pop("tags", [])
        thread = Thread(**validated_data)
        thread.save()
        apply_tags(thread, tags)
        return thread

    def update(self, instance, validated_data):
        tags = validated_data.pop("tags", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.body_html = ""  # пересчёт при следующем save
        instance.save()
        if tags is not None:
            instance.tags.clear()
            apply_tags(instance, tags)
        return instance


def apply_tags(thread: Thread, tag_names: list[str]) -> list[str]:
    """Создать/привязать теги и обновить usage_count (TECHSPEC §4.4)."""
    from shared.utils import slugify

    attached = []
    for name in tag_names[: TagWriteSerializer.MAX_TAGS]:
        slug = slugify(name, max_length=40)
        tag, _ = Tag.objects.get_or_create(slug=slug, defaults={"name": name[:40]})
        thread.tags.add(tag)
        attached.append(tag.slug)
        Tag.objects.filter(pk=tag.pk).update(usage_count=tag.threads.count())
    return attached


class ThreadDraftSerializer(serializers.ModelSerializer):
    """Автосохранение черновика раз в 10 секунд (TECHSPEC §4.4)."""

    class Meta:
        model = ThreadDraft
        fields = ["forum", "title", "body", "tags", "updated_at"]
        read_only_fields = ["updated_at"]


class ThreadPreviewSerializer(serializers.Serializer):
    """Предпросмотр markdown перед публикацией."""

    body = serializers.CharField(required=False, allow_blank=True)

    def validate_body(self, value):
        max_length = getattr(settings, "BODY_MAX_LENGTH", 50_000)
        if len(value) > max_length:
            raise serializers.ValidationError(f"Текст длиннее {max_length} символов")
        return value

    def to_representation(self, instance):
        return {"body_html": render_markdown(instance["body"])}
