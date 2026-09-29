"""Тесты тем, постов и реакций (TECHSPEC §11.5, §11.6)."""

import pytest

pytestmark = pytest.mark.django_db


# ── Разделы ────────────────────────────────────────────────────────
def test_forum_list_returns_roots(anon_client, forum):
    response = anon_client.get("/api/forums/")

    assert response.status_code == 200, response.data
    assert response.data["data"][0]["slug"] == "dev"
    assert response.data["meta"]["count"] == 1


def test_forum_detail_by_slug(anon_client, forum):
    response = anon_client.get(f"/api/forums/{forum.slug}/")

    assert response.status_code == 200, getattr(response, "data", response)
    assert response.data["data"]["name"] == "Разработка"


def test_forum_create_requires_admin(anon_client, auth_client, db):
    assert anon_client.post("/api/forums/", {"name": "X", "slug": "x"},
                            format="json").status_code in (401, 403)
    assert auth_client.post("/api/forums/", {"name": "X", "slug": "x"},
                            format="json").status_code == 403


# ── Темы ──────────────────────────────────────────────────────────
def test_thread_list_pagination_envelope(anon_client, thread):
    response = anon_client.get("/api/threads/")

    assert response.status_code == 200
    assert "data" in response.data and "meta" in response.data
    assert response.data["data"][0]["slug"] == thread.slug
    assert "next_cursor" in response.data["meta"]


def test_thread_create_by_member(auth_client, forum, user):
    response = auth_client.post("/api/threads/", {
        "forum": forum.slug,
        "title": "Новая тема про настройку среды",
        "body": "Подробное описание настройки локального окружения.",
        "tags": ["devops"],
    }, format="json")

    assert response.status_code == 201, response.data
    assert response.data["data"]["title"].startswith("Новая тема")
    assert response.data["data"]["author"]["id"] == user.pk


def test_thread_create_rejects_short_title(auth_client, forum):
    response = auth_client.post("/api/threads/", {
        "forum": forum.slug, "title": "Коротко", "body": "Текст темы достаточной длины.",
    }, format="json")

    assert response.status_code == 400
    assert any(e["field"] == "title" for e in response.data["errors"])


def test_thread_create_rejects_too_many_tags(auth_client, forum):
    response = auth_client.post("/api/threads/", {
        "forum": forum.slug,
        "title": "Тема с чрезмерным числом тегов",
        "body": "Текст темы достаточной длины для прохождения валидации.",
        "tags": ["a", "b", "c", "d", "e", "f"],
    }, format="json")

    assert response.status_code == 400
    assert any(e["field"] == "tags" for e in response.data["errors"])


def test_thread_detail_and_edit_permission(auth_client, thread, user):
    detail = auth_client.get(f"/api/threads/{thread.slug}/")
    assert detail.status_code == 200
    assert detail.data["data"]["can_edit"] is True

    update = auth_client.patch(f"/api/threads/{thread.slug}/", {
        "title": "Обновлённый заголовок темы достаточной длины",
    }, format="json")
    assert update.status_code == 200, update.data
    assert update.data["data"]["title"] == "Обновлённый заголовок темы достаточной длины"


def test_thread_soft_delete_marks_deleted(auth_client, thread):
    from apps.threads.models import Thread

    response = auth_client.delete(f"/api/threads/{thread.slug}/")
    assert response.status_code in (200, 204)
    assert Thread.all_objects.filter(pk=thread.pk, is_deleted=True).exists()


def test_thread_lock_blocks_new_posts(mod_client, auth_client, thread, moderator):
    lock = mod_client.post(f"/api/threads/{thread.slug}/lock/", {}, format="json")
    assert lock.status_code == 200, lock.data

    response = auth_client.post(f"/api/threads/{thread.slug}/posts/", {
        "body": "Ответ в закрытую тему, должен быть отклонён.",
    }, format="json")

    assert response.status_code in (400, 403)
    assert response.data["errors"]


# ── Посты ─────────────────────────────────────────────────────────
def test_post_creation_increments_counters(auth_client, thread):

    response = auth_client.post(f"/api/threads/{thread.slug}/posts/", {
        "body": "Развёрнутый ответ с пояснениями и примером кода.",
    }, format="json")

    assert response.status_code == 201, response.data
    thread.refresh_from_db()
    assert thread.posts_count == 1


def test_post_cannot_edit_other_users_post(auth_client, post, db):
    from apps.accounts.services import register_user

    other, _ = register_user(email="mallory@example.com", username="mallory",
                             password="Sup3rSecret!pass")
    other.is_email_verified = True
    other.save(update_fields=["is_email_verified"])
    other.userprofile.rank = "member"
    other.userprofile.save()

    auth_client.force_authenticate(other)
    response = auth_client.patch(f"/api/posts/{post.pk}/", {"body": "Взлом"}, format="json")

    assert response.status_code in (403, 404)
    post.refresh_from_db()
    assert post.body != "Взлом"


def test_quote_reference_creates_link(auth_client, thread, post):
    response = auth_client.post(f"/api/threads/{thread.slug}/posts/", {
        "body": "Ответ с цитатой предыдущего поста.",
        "parent": post.pk,
    }, format="json")

    assert response.status_code == 201, response.data
    assert response.data["data"]["parent_id"] == post.pk
    post.refresh_from_db()
    assert post.reply_count == 1


# ── Реакции ───────────────────────────────────────────────────────
def test_toggle_reaction_adds_and_removes(reactor_client, post, reaction):
    first = reactor_client.post(f"/api/posts/{post.pk}/react/", {"reaction": reaction.code},
                             format="json")
    assert first.status_code == 200, first.data
    assert first.data["data"]["active"] is True
    assert first.data["data"]["counts"][reaction.code] == 1

    second = reactor_client.post(f"/api/posts/{post.pk}/react/", {"reaction": reaction.code},
                                 format="json")
    assert second.data["data"]["active"] is False
    assert second.data["data"]["counts"][reaction.code] == 0


def test_reaction_rejects_unknown_code(auth_client, post):
    response = auth_client.post(f"/api/posts/{post.pk}/react/", {"reaction": "banana"},
                                format="json")

    assert response.status_code == 400
    assert response.data["errors"]


def test_reaction_requires_auth(anon_client, post, reaction):
    response = anon_client.post(f"/api/posts/{post.pk}/react/",
                                {"reaction": reaction.code}, format="json")

    assert response.status_code in (401, 403)
