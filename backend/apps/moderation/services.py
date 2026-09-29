"""Сервисы модерации: жалобы и действия над контентом (TECHSPEC §4.10)."""

from django.db import transaction
from django.utils import timezone

from shared.logging import get_logger, security_log

from .models import AuditLog, Ban, Flag, FlagStatus

logger = get_logger("forumos.moderation")


class ModerationError(Exception):
    """Ошибка модерации с кодом."""

    def __init__(self, message: str, code: str = "moderation_error"):
        super().__init__(message)
        self.message = message
        self.code = code


def create_flag(*, reporter, target_type: str, target_id: int, reason: str,
                comment: str = "") -> Flag:
    """Создать жалобу и опубликовать событие ``moderation.flag`` (TECHSPEC §4.10)."""
    existing = Flag.objects.filter(
        reporter=reporter, target_type=target_type, target_id=target_id
    ).first()
    if existing is not None:
        if existing.status != FlagStatus.OPEN:
            existing.status = FlagStatus.OPEN
            existing.resolved_at = None
            existing.resolved_by = None
            existing.save(update_fields=["status", "resolved_at", "resolved_by", "updated_at"])
            return existing
        return existing

    flag = Flag.objects.create(
        reporter=reporter, target_type=target_type, target_id=target_id,
        reason=reason, comment=comment[:1000],
    )

    from events.producer import publish_event

    publish_event("moderation.flag", {
        "flag_id": flag.pk,
        "target_type": target_type,
        "target_id": target_id,
        "reason": reason,
        "reporter_id": reporter.pk,
    })
    security_log("flag_created", flag_id=flag.pk, target_type=target_type,
                 target_id=target_id, reason=reason, reporter_id=reporter.pk)
    return flag


def resolve_flag(flag: Flag, moderator, comment: str = "") -> Flag:
    """Обработать жалобу (TECHSPEC §4.10)."""
    if flag.status != FlagStatus.OPEN:
        raise ModerationError("Жалоба уже обработана", code="already_resolved")

    flag.resolve(moderator, comment)
    AuditLog.log(actor=moderator, action=AuditLog.Action.RESOLVE_FLAG,
                 target_type=flag.target_type, target_id=flag.target_id,
                 flag_id=flag.pk, reason=flag.reason)

    target = flag.target
    if target is not None:
        from apps.notifications.services import create_notification

        user_id = getattr(target, "author_id", None) or getattr(target, "id", None)
        if user_id:
            create_notification(
                user_id=user_id, kind="system",
                payload={"message": "Ваш контент проверен модератором",
                         "flag_id": flag.pk, "reason": flag.reason},
            )
    return flag


def reject_flag(flag: Flag, moderator, comment: str = "") -> Flag:
    """Отклонить жалобу (TECHSPEC §4.10)."""
    if flag.status != FlagStatus.OPEN:
        raise ModerationError("Жалоба уже обработана", code="already_resolved")

    flag.reject(moderator, comment)
    AuditLog.log(actor=moderator, action=AuditLog.Action.REJECT_FLAG,
                 target_type=flag.target_type, target_id=flag.target_id,
                 flag_id=flag.pk, comment=comment[:500])
    return flag


# ── Действия модератора (TECHSPEC §4.10) ────────────────────────────
@transaction.atomic
def hide_post(post, moderator, reason: str = "") -> None:
    """Скрыть пост: soft-delete + аудит + уведомление автора."""
    from apps.posts.services import soft_delete_post

    if not post.can_delete(moderator):
        raise ModerationError("Недостаточно прав", code="forbidden")

    soft_delete_post(post, moderator)
    AuditLog.log(actor=moderator, action=AuditLog.Action.HIDE_POST,
                 target_type="post", target_id=post.pk, reason=reason)

    from apps.notifications.services import create_notification

    if post.author_id:
        create_notification(
            user_id=post.author_id, kind="system",
            payload={"message": f"Ваш пост скрыт модератором. Причина: {reason or '—'}",
                     "post_id": post.pk},
        )
    security_log("post_hidden", post_id=post.pk, moderator_id=moderator.pk, reason=reason)


@transaction.atomic
def delete_thread(thread, moderator, reason: str = "") -> None:
    """Удалить тему модератором."""
    from apps.threads.services import soft_delete_thread

    soft_delete_thread(thread, moderator, hard=True)
    AuditLog.log(actor=moderator, action=AuditLog.Action.DELETE_THREAD,
                 target_type="thread", target_id=thread.pk, reason=reason)


@transaction.atomic
def ban_user(*, target_user, moderator, duration: str = "1d", reason: str = "") -> Ban:
    """Забанить пользователя (TECHSPEC §4.10)."""
    if target_user.pk == moderator.pk:
        raise ModerationError("Нельзя забанить себя", code="self_ban")
    if target_user.is_superuser:
        raise ModerationError("Нельзя забанить суперпользователя", code="superuser_ban")

    ban = Ban.create_ban(user=target_user, moderator=moderator,
                          duration=duration, reason=reason)
    # Все выданные пользователю refresh-токены отзываются (TECHSPEC §4.10)
    _revoke_tokens(target_user)

    AuditLog.log(actor=moderator, action=AuditLog.Action.BAN_USER,
                 target_type="user", target_id=target_user.pk,
                 duration=duration, reason=reason)
    security_log("user_banned", user_id=target_user.pk, moderator_id=moderator.pk,
                 duration=duration)

    from apps.notifications.services import create_notification

    create_notification(user_id=target_user.pk, kind="system",
                        payload={"message": f"Ваш аккаунт заблокирован на {duration}"})
    return ban


def _revoke_tokens(target_user) -> int:
    """Добавить все outstanding-токены пользователя в blacklist (TECHSPEC §4.10)."""
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    revoked = 0
    tokens = OutstandingToken.objects.filter(user=target_user).exclude(
        blacklistedtoken__isnull=False
    )
    for token in tokens:
        _outstanding, _created = BlacklistedToken.objects.get_or_create(token=token)
        revoked += 1
    return revoked


def unban_user(*, target_user, moderator) -> None:
    """Снять бан (TECHSPEC §4.10)."""
    Ban.objects.filter(user=target_user, is_active=True).update(
        is_active=False, lifted_at=timezone.now(), lifted_by=moderator
    )
    AuditLog.log(actor=moderator, action=AuditLog.Action.UNBAN_USER,
                 target_type="user", target_id=target_user.pk)
    security_log("user_unbanned", user_id=target_user.pk, moderator_id=moderator.pk)


def warn_user(*, target_user, moderator, message: str) -> None:
    """Предупредить пользователя (TECHSPEC §4.10)."""
    AuditLog.log(actor=moderator, action=AuditLog.Action.WARN_USER,
                 target_type="user", target_id=target_user.pk, message=message[:500])

    from apps.notifications.services import create_notification

    create_notification(user_id=target_user.pk, kind="system",
                        payload={"message": f"Предупреждение от модератора: {message}"})
    security_log("user_warned", user_id=target_user.pk, moderator_id=moderator.pk)
