"""SEO: robots.txt, sitemap, OG-картинки, мета-записи (TECHSPEC §4.11, §14, §16)."""

import pytest

from apps.seo.models import SEOMeta


@pytest.mark.django_db
def test_robots_txt(anon_client):
    response = anon_client.get("/robots.txt")

    assert response.status_code == 200
    body = response.content.decode()
    assert "User-agent: *" in body
    assert "Disallow: /api/" in body
    assert "Sitemap:" in body


@pytest.mark.django_db
def test_sitemap_index(anon_client):
    response = anon_client.get("/sitemap.xml")

    assert response.status_code == 200
    assert b"<sitemapindex" in response.content


@pytest.mark.django_db
def test_thread_sitemap_lists_thread(anon_client, thread):
    response = anon_client.get("/sitemap-threads.xml")

    assert response.status_code == 200
    body = response.content.decode()
    assert f"/t/{thread.slug}" in body


@pytest.mark.django_db
def test_forum_sitemap_lists_forum(anon_client, forum):
    response = anon_client.get("/sitemap-forums.xml")

    assert response.status_code == 200
    assert f"/f/{forum.slug}" in response.content.decode()


@pytest.mark.django_db
def test_user_sitemap_lists_user(anon_client, user):
    response = anon_client.get("/sitemap-users.xml")

    assert response.status_code == 200
    assert f"/u/{user.username}" in response.content.decode()


@pytest.mark.django_db
def test_og_image_for_thread(anon_client, thread):
    response = anon_client.get(f"/og/thread/{thread.slug}.png")

    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.django_db
def test_og_image_for_unknown_slug(anon_client):
    response = anon_client.get("/og/thread/nonexistent.png")

    assert response.status_code == 404


@pytest.mark.django_db
def test_seo_meta_for_path_priority(mod_client):
    created = mod_client.post("/api/seo/meta/", {
        "path": "/t/vanilla",
        "title": "Vanilla — сообщество",
        "description": "Описание",
        "priority": 10,
    }, format="json")

    assert created.status_code == 201, created.data
    assert created.data["data"]["priority"] == 10


@pytest.mark.django_db
def test_seo_resolve_returns_meta(anon_client):
    SEOMeta.objects.create(path="/t/vanilla", title="Vanilla", description="Описание")

    response = anon_client.get("/api/seo/resolve/?path=/t/vanilla")

    assert response.status_code == 200, response.data
    assert response.data["data"]["title"] == "Vanilla"


@pytest.mark.django_db
def test_seo_resolve_missing_is_404(anon_client):
    response = anon_client.get("/api/seo/resolve/?path=/t/nothing")

    assert response.status_code == 404
    assert response.data["data"] is None


@pytest.mark.django_db
def test_seo_meta_crud_requires_moderator(auth_client, mod_client):
    assert auth_client.get("/api/seo/meta/").status_code == 403

    created = mod_client.post("/api/seo/meta/", {"path": "/f/dev", "title": "Dev"},
                              format="json")
    assert created.status_code == 201, created.data

    updated = mod_client.patch(f"/api/seo/meta/{created.data['data']['id']}/",
                               {"title": "Разработка"}, format="json")
    assert updated.status_code == 200, updated.data
    assert updated.data["data"]["title"] == "Разработка"

    deleted = mod_client.delete(f"/api/seo/meta/{created.data['data']['id']}/")
    assert deleted.status_code == 204
