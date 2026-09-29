"""Общие фикстуры для тестов ForumOS (TECHSPEC §16)."""

import pytest

from apps.accounts.services import register_user

from .utils import EnvelopeAPIClient

PASSWORD = "Sup3rSecret!pass"


def _make_user(username: str, email: str, **kwargs):
    user, _raw_token = register_user(
        email=email, username=username, password=PASSWORD, **kwargs
    )
    user.is_email_verified = True
    user.save(update_fields=["is_email_verified"])
    return user


@pytest.fixture
def api_client():
    return EnvelopeAPIClient()


@pytest.fixture
def api_client_factory():
    """Фабрика клиентов — для проверок реальной JWT-аутентификации."""
    return EnvelopeAPIClient


@pytest.fixture
def user(db):
    """Обычный пользователь с рангом member."""
    from apps.accounts.models import Rank

    created = _make_user("alice", "alice@example.com")
    profile = created.userprofile
    profile.reputation = 120
    profile.rank = Rank.MEMBER
    profile.save()
    return created


@pytest.fixture
def new_user(db):
    """Пользователь без подтверждения email."""
    user, _raw_token = register_user(
        email="carol@example.com", username="carol", password=PASSWORD
    )
    return user


@pytest.fixture
def moderator(db):
    """Модератор с правами staff."""
    created = _make_user("mod_octavian", "mod@example.com")
    created.is_staff = True
    created.is_superuser = True
    created.save(update_fields=["is_staff", "is_superuser"])
    return created


@pytest.fixture
def auth_client(user):
    """Отдельный клиент, авторизованный как обычный пользователь."""
    client = EnvelopeAPIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def mod_client(moderator):
    """Отдельный клиент, авторизованный как модератор."""
    client = EnvelopeAPIClient()
    client.force_authenticate(moderator)
    return client


@pytest.fixture
def other_user(db):
    """Второй обычный участник — для проверок «нельзя применить к себе»."""
    from apps.accounts.models import Rank

    created = _make_user("bob", "bob@example.com")
    profile = created.userprofile
    profile.rank = Rank.MEMBER
    profile.save()
    return created


@pytest.fixture
def reactor_client(other_user):
    """Клиент, авторизованный как ``other_user``."""
    client = EnvelopeAPIClient()
    client.force_authenticate(other_user)
    return client


@pytest.fixture
def anon_client(api_client):
    return api_client


@pytest.fixture
def reaction(db):
    """Тип реакции из справочника (TECHSPEC §10.2)."""
    from apps.reactions.models import Reaction

    return Reaction.objects.create(code="like", emoji="👍", karma_value=1, order=1)


@pytest.fixture
def forum(db):
    from apps.forums.models import Forum

    return Forum.objects.create(name="Разработка", slug="dev", order=1)


@pytest.fixture
def thread(db, forum, user):
    from apps.threads.services import create_thread

    return create_thread(
        author=user,
        forum=forum,
        title="Как настроить локальный ForumOS",
        body="Описываю пошаговую настройку проекта и запуск всех контейнеров.",
        tags=["devops", "guide"],
    )


@pytest.fixture
def post(db, thread, user):
    from apps.posts.services import create_post

    return create_post(
        thread=thread,
        author=user,
        body="Первый ответ в теме, проверяем создание поста и счётчики.",
    )
