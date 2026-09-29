"""Сериализаторы аккаунтов (TECHSPEC §11.2, §11.3)."""

from django.contrib.auth import get_user_model
from rest_framework import serializers

from shared.validators import validate_email, validate_password, validate_username

from .models import Achievement, Theme, UserAchievement, UserProfile

UserModel = get_user_model()


class AchievementSerializer(serializers.ModelSerializer):
    """Ачивка (TECHSPEC §4.6)."""

    unlocked = serializers.SerializerMethodField()
    unlocked_at = serializers.SerializerMethodField()

    class Meta:
        model = Achievement
        fields = ["code", "title", "description", "icon", "unlocked", "unlocked_at"]

    def get_unlocked(self, obj) -> bool:
        return obj.pk in (self.context.get("unlocked_ids") or ())

    def get_unlocked_at(self, obj):
        return (self.context.get("unlocked_map") or {}).get(obj.pk)


class UserProfileSerializer(serializers.ModelSerializer):
    """Публичные данные профиля."""

    avatar = serializers.SerializerMethodField()
    rank_display = serializers.CharField(read_only=True)
    is_online = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = ["bio", "location", "website", "avatar", "reputation", "rank",
                  "rank_display", "is_online", "last_seen_at", "threads_count",
                  "posts_count", "reactions_received", "created_at"]

    def get_avatar(self, obj) -> str | None:
        if not obj.avatar:
            return None
        try:
            return obj.avatar.url
        except ValueError:  # pragma: no cover
            return None

    def get_is_online(self, obj) -> bool:
        return obj.is_online


class UserSerializer(serializers.ModelSerializer):
    """Публичное представление пользователя (TECHSPEC §11.3)."""

    avatar = serializers.SerializerMethodField()
    reputation = serializers.IntegerField(source="userprofile.reputation", read_only=True,
                                          default=0)
    rank = serializers.CharField(source="userprofile.rank", read_only=True)
    rank_display = serializers.CharField(source="userprofile.rank_display", read_only=True)
    bio = serializers.CharField(source="userprofile.bio", read_only=True, default="")
    location = serializers.CharField(source="userprofile.location", read_only=True, default="")
    website = serializers.CharField(source="userprofile.website", read_only=True, default="")
    is_online = serializers.SerializerMethodField()
    last_seen_at = serializers.DateTimeField(source="userprofile.last_seen_at", read_only=True)

    class Meta:
        model = UserModel
        fields = ["id", "username", "avatar", "reputation", "rank", "rank_display",
                  "bio", "location", "website", "is_online", "last_seen_at", "created_at"]
        read_only_fields = fields

    def get_avatar(self, obj) -> str | None:
        return obj.avatar_url

    def get_is_online(self, obj) -> bool:
        profile = getattr(obj, "userprofile", None)
        return bool(profile and profile.is_online)


class UserMeSerializer(UserSerializer):
    """Текущий пользователь: + email, настройки, ачивки (TECHSPEC §4.2)."""

    email = serializers.EmailField(read_only=True)
    is_email_verified = serializers.BooleanField(read_only=True)
    is_staff = serializers.BooleanField(read_only=True)
    theme = serializers.CharField(source="userprofile.theme", read_only=True)
    show_online_status = serializers.BooleanField(source="userprofile.show_online_status",
                                                  read_only=True)
    notify_replies = serializers.BooleanField(source="userprofile.notify_replies", read_only=True)
    notify_mentions = serializers.BooleanField(source="userprofile.notify_mentions",
                                               read_only=True)
    notify_reactions = serializers.BooleanField(source="userprofile.notify_reactions",
                                                read_only=True)
    achievements = serializers.SerializerMethodField()
    rank_progress = serializers.SerializerMethodField()

    class Meta(UserSerializer.Meta):
        fields = [
            *UserSerializer.Meta.fields,
            "email", "is_email_verified", "is_staff", "theme", "show_online_status",
            "notify_replies", "notify_mentions", "notify_reactions",
            "achievements", "rank_progress",
        ]
        read_only_fields = fields

    def get_achievements(self, obj):
        unlocked = {ua.achievement_id: ua for ua in obj.achievements.select_related("achievement")}
        return AchievementSerializer(
            Achievement.objects.all(),
            many=True,
            context={
                "unlocked_ids": set(unlocked.keys()),
                "unlocked_map": {aid: ua.unlocked_at for aid, ua in unlocked.items()},
            },
        ).data

    def get_rank_progress(self, obj):
        return obj.userprofile.rank_progress


class UserUpdateSerializer(serializers.ModelSerializer):
    """PATCH /api/users/me/ — обновление профиля и настроек (TECHSPEC §4.2)."""

    bio = serializers.CharField(max_length=500, required=False, allow_blank=True)
    location = serializers.CharField(max_length=64, required=False, allow_blank=True)
    website = serializers.URLField(max_length=200, required=False, allow_blank=True)
    theme = serializers.ChoiceField(choices=Theme.choices, required=False)
    show_online_status = serializers.BooleanField(required=False)
    notify_replies = serializers.BooleanField(required=False)
    notify_mentions = serializers.BooleanField(required=False)
    notify_reactions = serializers.BooleanField(required=False)
    username = serializers.CharField(max_length=32, required=False)

    class Meta:
        model = UserModel
        fields = ["username", "bio", "location", "website", "theme", "show_online_status",
                  "notify_replies", "notify_mentions", "notify_reactions"]

    def validate_username(self, value):
        validate_username(value)
        qs = UserModel.objects.filter(username__iexact=value).exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Имя пользователя уже занято")
        return value

    def validate_website(self, value):
        return value or ""

    def to_representation(self, instance):
        return UserMeSerializer(instance, context=self.context).data


class PasswordChangeSerializer(serializers.Serializer):
    """Смена пароля собственным пользователем (TECHSPEC §4.2)."""

    old_password = serializers.CharField(write_only=True, style={"input_type": "password"})
    new_password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_new_password(self, value):
        validate_password(value)
        return value


class AccountDeleteSerializer(serializers.Serializer):
    """Удаление аккаунта с подтверждением паролем (TECHSPEC §4.2)."""

    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Пароль указан неверно")
        return value


# ── Auth (TECHSPEC §11.2) ───────────────────────────────────────────
class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    username = serializers.CharField(max_length=32)
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_email(self, value):
        validate_email(value.strip().lower())
        return value.strip().lower()

    def validate_username(self, value):
        validate_username(value.strip())
        return value.strip()

    def validate_password(self, value):
        validate_password(value)
        return value


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_email(self, value):
        return value.strip().lower()


class PasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=128)
    new_password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_new_password(self, value):
        validate_password(value)
        return value


class EmailVerificationSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=128)


class PublicAchievementSerializer(serializers.ModelSerializer):
    """Ачивки конкретного пользователя для публичного профиля."""

    class Meta:
        model = UserAchievement
        fields = ["achievement", "unlocked_at"]
