"""Сервисы аккаунтов: регистрация, токены, пароль (TECHSPEC §4.1)."""

import hashlib

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from shared.logging import get_logger, security_log
from shared.utils import client_ip, random_token
from shared.validators import validate_email, validate_password, validate_username

from .models import Achievement, User, UserAchievement, UserProfile, VerificationToken

logger = get_logger("forumos.accounts.services")

UserModel = get_user_model()


class ServiceError(Exception):
    """Доменная ошибка сервиса с машиночитаемым кодом."""

    def __init__(self, message: str, code: str = "service_error", field: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.field = field

    def as_error(self) -> dict:
        return {"code": self.code, "field": self.field, "message": self.message}


def hash_token(raw_token: str) -> str:
    """SHA-256 хэш токена (в БД хранится только хэш)."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


# ── Регистрация ─────────────────────────────────────────────────────
@transaction.atomic
def register_user(*, email: str, username: str, password: str, request=None) -> tuple[User, str]:
    """Создать пользователя и вернуть (user, raw_verification_token).

    Порождает событие ``user.joined`` (TECHSPEC §13.1).
    """
    email = (email or "").strip().lower()
    username = (username or "").strip()

    validate_email(email)
    validate_username(username)
    validate_password(password)

    if UserModel.objects.filter(email__iexact=email).exists():
        raise ServiceError("Пользователь с таким email уже существует",
                           code="email_taken", field="email")
    if UserModel.objects.filter(username__iexact=username).exists():
        raise ServiceError("Имя пользователя уже занято", code="username_taken", field="username")

    try:
        user = UserModel.objects.create_user(
            email=email, username=username, password=password, is_active=True
        )
    except IntegrityError as exc:  # pragma: no cover - гонка на уровне БД
        raise ServiceError("Данные уже заняты", code="conflict") from exc

    logger.info("user_created", user_id=user.pk, email=email,
                ip=client_ip(request) if request else None)

    raw_token = issue_token(user, VerificationToken.Purpose.EMAIL_VERIFICATION)
    return user, raw_token


# ── Токены ──────────────────────────────────────────────────────────
def issue_token(user, purpose: str) -> str:
    """Выдать токен цели (raw) и сохранить его хэш. Старые токиены инвалидируются."""
    raw = random_token(32)
    VerificationToken.objects.filter(user=user, purpose=purpose).delete()
    VerificationToken.objects.create(
        user=user,
        token_hash=hash_token(raw),
        purpose=purpose,
        expires_at=timezone.now() + VerificationToken.expiry_for(purpose),
    )
    logger.info("token_issued", user_id=user.pk, purpose=purpose)
    return raw


def resolve_token(raw_token: str, purpose: str) -> VerificationToken:
    """Найти действующий токен по raw-значению."""
    if not raw_token:
        raise ServiceError("Токен не указан", code="token_required", field="token")

    token = VerificationToken.objects.filter(
        token_hash=hash_token(raw_token), purpose=purpose
    ).select_related("user").first()

    if token is None:
        raise ServiceError("Недействительный токен", code="invalid_token", field="token")
    if token.used_at is not None:
        raise ServiceError("Токен уже использован", code="token_used", field="token")
    if token.is_expired:
        raise ServiceError("Срок действия токена истёк", code="token_expired", field="token")
    if not token.user.is_active:
        raise ServiceError("Аккаунт отключён", code="account_disabled")
    return token


@transaction.atomic
def verify_email(raw_token: str) -> User:
    """Подтвердить email по токену (TECHSPEC §4.1)."""
    token = resolve_token(raw_token, VerificationToken.Purpose.EMAIL_VERIFICATION)
    user = token.user
    user.is_email_verified = True
    user.save(update_fields=["is_email_verified", "updated_at"])
    token.mark_used()

    # Подтверждённый email поднимает ранг минимум до Member (TECHSPEC §4.6)
    profile, _ = UserProfile.objects.get_or_create(user=user)
    if profile.rank == "newbie":
        profile.rank = "member"
        profile.save(update_fields=["rank", "updated_at"])
    logger.info("email_verified", user_id=user.pk)
    return user


def resend_verification(user) -> str:
    """Повторная отправка письма подтверждения (TECHSPEC §4.1)."""
    if user.is_email_verified:
        raise ServiceError("Email уже подтверждён", code="already_verified", field="email")
    raw = issue_token(user, VerificationToken.Purpose.EMAIL_VERIFICATION)
    send_verification_email(user, raw)
    return raw


# ── Пароль ──────────────────────────────────────────────────────────
def request_password_reset(email: str, request=None) -> bool:
    """Сброс пароля по email.

    Всегда возвращает True (не раскрываем наличие аккаунта).
    """
    email = (email or "").strip().lower()
    user = UserModel.objects.filter(email__iexact=email, is_active=True).first()
    if user is None:
        security_log("password_reset_unknown_email", email=email,
                     ip=client_ip(request) if request else None)
        return False

    raw = issue_token(user, VerificationToken.Purpose.PASSWORD_RESET)
    send_password_reset_email(user, raw)
    return True


@transaction.atomic
def confirm_password_reset(raw_token: str, new_password: str) -> User:
    """Установить новый пароль по токену (TECHSPEC §4.1)."""
    validate_password(new_password)
    token = resolve_token(raw_token, VerificationToken.Purpose.PASSWORD_RESET)
    user = token.user
    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])
    token.mark_used()

    # Все активные сессии сбрасываются
    from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

    OutstandingToken.objects.filter(user=user).update(
        revoked_at=timezone.now()
    )
    security_log("password_changed_by_reset", user_id=user.pk)
    return user


@transaction.atomic
def change_password(user, old_password: str, new_password: str) -> User:
    """Самостоятельная смена пароля (TECHSPEC §4.2)."""
    if not user.check_password(old_password):
        raise ServiceError("Текущий пароль указан неверно",
                           code="invalid_password", field="old_password")
    validate_password(new_password)
    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])
    security_log("password_changed", user_id=user.pk)
    return user


# ── Вход ────────────────────────────────────────────────────────────
def login_user(*, email: str, password: str, request=None) -> User:
    """Аутентификация с аудитом попыток (TECHSPEC §4.1)."""
    email = (email or "").strip().lower()
    user = authenticate(username=email, password=password)

    if user is None:
        security_log("login_failed", email=email, ip=client_ip(request) if request else None)
        raise ServiceError("Неверный email или пароль", code="invalid_credentials")
    if not user.is_active:
        security_log("login_blocked_inactive", user_id=user.pk)
        raise ServiceError("Аккаунт отключён", code="account_disabled")
    if user.is_deleted:
        security_log("login_blocked_deleted", user_id=user.pk)
        raise ServiceError("Аккаунт удалён", code="account_deleted")
    if user.is_banned:
        from apps.moderation.models import Ban

        ban = Ban.active_for(user.pk)
        security_log("login_blocked_banned", user_id=user.pk,
                     duration=ban.duration if ban else None)
        raise ServiceError("Аккаунт заблокирован", code="account_banned")

    logger.info("login_success", user_id=user.pk, email=email)
    return user


# ── Email (TECHSPEC §4.1) ───────────────────────────────────────────
def send_verification_email(user, raw_token: str) -> bool:
    from django.core.mail import send_mail

    link = f"{settings.APP_HOST}/verify-email?token={raw_token}"
    return send_mail(
        subject="Подтвердите email в ForumOS",
        message=(
            f"Здравствуйте, {user.username}!\n\n"
            f"Подтвердите email, перейдя по ссылке (действует "
            f"{settings.EMAIL_VERIFICATION_TTL_HOURS} ч):\n{link}\n\n"
            f"Если вы не регистрировались — просто проигнорируйте письмо."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


def send_password_reset_email(user, raw_token: str) -> bool:
    from django.core.mail import send_mail

    link = f"{settings.APP_HOST}/reset-password/confirm?token={raw_token}"
    return send_mail(
        subject="Сброс пароля в ForumOS",
        message=(
            f"Здравствуйте, {user.username}!\n\n"
            f"Для смены пароля перейдите по ссылке (действует "
            f"{settings.PASSWORD_RESET_TTL_HOURS} ч):\n{link}\n\n"
            f"Если вы не запрашивали сброс — проигнорируйте письмо."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


# ── Профиль ─────────────────────────────────────────────────────────
def update_profile(user, data: dict) -> UserProfile:
    """Обновить профиль пользователя (TECHSPEC §4.2)."""
    profile, _ = UserProfile.objects.get_or_create(user=user)
    allowed = {"bio", "location", "website", "theme", "show_online_status",
               "notify_replies", "notify_mentions", "notify_reactions"}
    for field, value in data.items():
        if field in allowed and value is not None:
            setattr(profile, field, value)
    profile.save()
    logger.info("profile_updated", user_id=user.pk, fields=list(data.keys()))
    return profile


def touch_last_seen(user_id: int) -> None:
    """Обновить время последнего онлайна (TECHSPEC §4.8)."""
    UserProfile.objects.filter(user_id=user_id).update(last_seen_at=timezone.now())


def apply_reputation(user_id: int, delta: int, reason: str = "") -> int:
    """Изменить репутацию пользователя (TECHSPEC §4.6).

    Обёртка над профилем: вызывается обработчиками событий Kafka
    и сервисами контента, не зная о внутренностях профиля.
    """
    profile = UserProfile.objects.filter(user_id=user_id).first()
    if profile is None:
        return 0
    profile.add_reputation(delta, reason=reason)
    return profile.reputation


def increment_profile_counter(user_id: int, field: str, delta: int = 1) -> None:
    """Изменить счётчик профиля (threads_count / posts_count / reactions_received)."""
    if field not in ("threads_count", "posts_count", "reactions_received"):
        raise ValueError(f"Неизвестный счётчик: {field}")
    UserProfile.objects.filter(user_id=user_id).update(**{field: models.F(field) + delta})


# ── Ачивки (TECHSPEC §4.6) ──────────────────────────────────────────
ACHIEVEMENT_SEED: list[dict] = [
    {"code": "first-post", "title": "Первый пост", "description": "Опубликовать первый пост",
     "icon": "🎉", "kind": Achievement.Kind.POSTS, "threshold": 1, "order": 1},
    {"code": "ten-threads", "title": "10 тем", "description": "Создать 10 тем",
     "icon": "✍️", "kind": Achievement.Kind.THREADS, "threshold": 10, "order": 2},
    {"code": "hundred-posts", "title": "100 постов", "description": "Написать 100 постов",
     "icon": "📝", "kind": Achievement.Kind.POSTS, "threshold": 100, "order": 3},
    {"code": "thousand-likes", "title": "1000 лайков", "description": "Получить 1000 реакций",
     "icon": "🔥", "kind": Achievement.Kind.REACTIONS, "threshold": 1000, "order": 4},
    {"code": "reputation-500", "title": "Репутация 500", "description": "Достичь 500 репутации",
     "icon": "⭐", "kind": Achievement.Kind.REPUTATION, "threshold": 500, "order": 5},
    {"code": "first-thread-100", "title": "Сотня ответов",
     "description": "Создать тему со 100+ ответами", "icon": "🏆",
     "kind": Achievement.Kind.SPECIAL, "threshold": 100, "order": 6},
]


def seed_achievements() -> list[Achievement]:
    """Наполнить каталог ачивок из ТЗ (TECHSPEC §4.6)."""
    result = []
    for item in ACHIEVEMENT_SEED:
        achievement, _ = Achievement.objects.update_or_create(
            code=item["code"], defaults=item
        )
        result.append(achievement)
    logger.info("achievements_seeded", count=len(result))
    return result


def evaluate_achievements(user_id: int) -> list[Achievement]:
    """Проверить и выдать достижения пользователя (TECHSPEC §4.6).

    Событие ``achievement.unlocked`` уходит в Kafka (TECHSPEC §13.1).
    """
    profile = UserProfile.objects.filter(user_id=user_id).first()
    if profile is None:
        return []

    unlocked_ids = set(
        UserAchievement.objects.filter(user=user_id).values_list("achievement_id", flat=True)
    )
    unlocked: list[Achievement] = []

    for achievement in Achievement.objects.all():
        if achievement.id in unlocked_ids:
            continue
        if not achievement.is_unlocked_for(profile):
            continue

        # «Сотня ответов» — специальная проверка по темам пользователя
        if achievement.code == "first-thread-100":
            from apps.threads.models import Thread

            has_big_thread = (
                Thread.objects.filter(author_id=user_id, is_deleted=False,
                                      posts_count__gte=100).exists()
            )
            if not has_big_thread:
                continue

        UserAchievement.objects.create(user_id=user_id, achievement=achievement)
        unlocked.append(achievement)

        from events.producer import publish_event

        publish_event("achievement.unlocked", {
            "user_id": user_id,
            "achievement_code": achievement.code,
            "title": achievement.title,
            "icon": achievement.icon,
        })

        from apps.notifications.services import create_notification

        create_notification(
            user_id=user_id,
            kind="system",
            payload={
                "actor_username": None,
                "achievement": achievement.code,
                "title": achievement.title,
                "icon": achievement.icon,
                "message": f"Ачивка «{achievement.title}»",
            },
        )

    if unlocked:
        logger.info("achievements_unlocked", user_id=user_id,
                    codes=[a.code for a in unlocked])
    return unlocked
