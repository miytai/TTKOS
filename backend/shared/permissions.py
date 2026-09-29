"""Permissions ForumOS (TECHSPEC §15.2)."""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from .logging import get_logger

logger = get_logger("forumos.permissions")


def user_can_moderate(user, forum) -> bool:
    """Модератор раздела или администратор."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return bool(forum and getattr(forum, "moderator_id", None) == user.id)


class IsAuthorOrReadOnly(BasePermission):
    """Изменение/удаление — только автором или модератором."""

    message = "Редактировать и удалять контент может только автор"

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if not request.user.is_authenticated:
            return False
        if getattr(request.user, "is_staff", False) or request.user.is_superuser:
            return True

        author_id = getattr(obj, "author_id", None) or getattr(obj, "user_id", None)
        if author_id == request.user.id:
            return True

        # Модератор раздела, к которому относится объект
        forum = getattr(obj, "forum", None)
        if forum is None and hasattr(obj, "thread"):
            forum = obj.thread.forum
        return user_can_moderate(request.user, forum)


class IsModerator(BasePermission):
    """Только модератор (раздела) или администратор."""

    message = "Недостаточно прав для модерации"

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_staff or request.user.is_superuser)
        )

    def has_object_permission(self, request, view, obj):
        return user_can_moderate(request.user, getattr(obj, "forum", None))


class IsAdmin(BasePermission):
    """Только администратор (staff/superuser)."""

    message = "Доступ только для администраторов"

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated
                    and (request.user.is_staff or request.user.is_superuser))


class CanCreateThread(BasePermission):
    """Создание тем — для подтверждённых пользователей (TECHSPEC §4.3)."""

    message = "Создавать темы может только пользователь с подтверждённым email"

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser or user.is_staff:
            return True
        return bool(getattr(user, "is_email_verified", False))


class CanPostInForum(BasePermission):
    """Проверка прав на публикацию в конкретном разделе (TECHSPEC §4.3)."""

    message = "Публикация в этом разделе недоступна"

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated)


class IsNotBanned(BasePermission):
    """Забаненные пользователи не могут создавать контент (TECHSPEC §4.10)."""

    message = "Аккаунт заблокирован"

    def has_permission(self, request, view):
        from apps.moderation.models import Ban

        user = request.user
        if not user or not user.is_authenticated:
            return True
        if request.method in SAFE_METHODS:
            return True
        return not Ban.is_banned(user.pk)
