"""Сигналы приложения accounts (TECHSPEC §4.1, §4.6)."""

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from shared.logging import get_logger, security_log

logger = get_logger("forumos.accounts")


@receiver(post_save, sender="accounts.User", dispatch_uid="forumos_create_profile")
def create_user_profile(sender, instance, created, **kwargs):
    """Создание профиля сразу после регистрации (TECHSPEC §4.1)."""
    if not created:
        return
    from apps.accounts.models import UserProfile

    profile, _ = UserProfile.objects.get_or_create(user=instance)
    logger.info("user_registered", user_id=instance.pk, username=instance.username)
    # Событие для подписчиков Kafka (welcome-цепочка, аналитика)
    from events.producer import publish_event

    publish_event(
        "user.joined",
        {"user_id": instance.pk, "username": instance.username,
         "profile_id": profile.pk, "created_at": instance.created_at.isoformat()},
    )


@receiver(user_logged_in, dispatch_uid="forumos_login_log")
def on_login(sender, request, user, **kwargs):
    """Фиксация входа и обновление last_seen_at (TECHSPEC §5.8)."""
    from apps.accounts.models import UserProfile

    UserProfile.objects.filter(user=user).update(last_seen_at=timezone.now())
    security_log(
        "login",
        user_id=user.pk,
        username=user.username,
        ip=getattr(request, "client_ip", None),
        backend=getattr(request, "backend", None),
    )


@receiver(user_logged_out, dispatch_uid="forumos_logout_log")
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        security_log("logout", user_id=user.pk, username=user.username)


@receiver(pre_save, sender="accounts.User", dispatch_uid="forumos_user_audit")
def on_user_change(sender, instance, **kwargs):
    """Логирование смены email/username для аудита (TECHSPEC §5.8)."""
    if not instance.pk:
        return
    previous = sender.objects.filter(pk=instance.pk).first()
    if previous is None:
        return
    changed = []
    if previous.email != instance.email:
        changed.append("email")
    if previous.username != instance.username:
        changed.append("username")
    if changed:
        security_log("user_identity_changed", user_id=instance.pk,
                     username=instance.username, fields=changed)
