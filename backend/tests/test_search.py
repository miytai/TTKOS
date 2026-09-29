"""Поиск: Elasticsearch-контракт и деградация без ES (TECHSPEC §4.7, §16)."""

import pytest

from apps.search import service
from apps.search.service import SORTS


class FakeIndices:
    def __init__(self, client):
        self.client = client

    def exists(self, index):
        return index in self.client.existing

    def create(self, index, **body):
        self.client.existing.add(index)
        self.client.created.append((index, body))


class FakeElastic:
    """Минимальная заглушка клиента Elasticsearch 8.x."""

    def __init__(self, hits=None):
        self.existing = set()
        self.created = []
        self.indexed = []
        self.searches = []
        self.hits = hits or {"hits": {"total": {"value": 0}, "hits": []}}
        self.indices = FakeIndices(self)

    def index(self, index, id, document, refresh=False):
        self.indexed.append((index, id, document))
        return {"result": "created"}

    def delete(self, index, id, **kwargs):
        self.indexed.append((index, id, None))
        return {"result": "deleted"}

    def search(self, index, body):
        self.searches.append((index, body))
        return self.hits

    def ping(self):
        return True

    def delete_by_query(self, index, body, **kwargs):
        return {"deleted": 3}


@pytest.fixture
def fake_es(monkeypatch):
    client = FakeElastic()
    monkeypatch.setattr(service, "_client", client)
    return client


@pytest.mark.django_db
def test_ensure_indices_is_idempotent(fake_es):
    first = service.ensure_indices()
    second = service.ensure_indices()

    assert len(first) == 3
    assert second == []
    assert "forumos-threads" in fake_es.existing


@pytest.mark.django_db
def test_index_and_delete_document(fake_es):
    assert service.index_document("threads", 7, {"id": 7, "title": "Тема"}, refresh=True)
    assert fake_es.indexed[0][0] == "forumos-threads"
    assert fake_es.indexed[0][1] == 7

    service.delete_document("threads", 7)
    assert fake_es.indexed[1][2] is None


@pytest.mark.django_db
def test_thread_payload_from_model(thread):
    doc = service.thread_document(thread)

    assert doc["id"] == thread.pk
    assert doc["slug"] == thread.slug
    assert doc["author_username"] == thread.author.username
    assert doc["forum_slug"] == thread.forum.slug
    assert "devops" in doc["tags"]


@pytest.mark.django_db
def test_search_builds_query(fake_es, monkeypatch):
    fake_es.hits = {"hits": {"total": {"value": 1}, "hits": [{
        "_id": "5", "_score": 1.5,
        "_source": {"id": 5, "title": "Тема про Docker", "body": "docker compose up",
                    "author_username": "alice", "forum_slug": "dev",
                    "tags": ["devops"], "slug": "docker"},
        "highlight": {"title": ["<em>Тема</em> про Docker"]},
    }]}}

    result = service.search("threads", "docker", filters={"forum": "dev"},
                            ordering="newest", limit=5, offset=0)

    index, body = fake_es.searches[0]
    assert index == "forumos-threads"
    must = body["query"]["bool"]["must"][0]["multi_match"]
    assert must["query"] == "docker"
    assert body["query"]["bool"]["filter"] == [
        {"bool": {"filter": [{"term": {"forum_slug": "dev"}}]}}
    ]
    assert body["size"] == 5
    assert body["sort"] == SORTS["newest"]

    assert result["total"] == 1
    hit = result["results"][0]
    assert hit["url"] == "/t/docker"
    assert hit["entity"] == "threads"
    assert "Тема" in hit["snippet"]


@pytest.mark.django_db
def test_search_empty_query_returns_nothing(fake_es):
    assert service.search("threads", "") == {"total": 0, "results": []}
    assert fake_es.searches == []


@pytest.mark.django_db
def test_search_degrades_without_elastic(monkeypatch):
    monkeypatch.setattr(service, "_client", None)
    monkeypatch.setattr(service, "get_client", lambda: None)

    result = service.search("threads", "docker")

    assert result == {"total": 0, "results": []}
    assert service.index_document("threads", 1, {"id": 1}) is False
    assert service.ensure_indices() == []


@pytest.mark.django_db
def test_autocomplete_uses_database(thread):
    suggestions = service.autocomplete("настроить")

    assert len(suggestions) == 1
    assert suggestions[0]["type"] == "thread"
    assert suggestions[0]["value"] == f"/t/{thread.slug}"


@pytest.mark.django_db
def test_autocomplete_ignores_short_query():
    assert service.autocomplete("d") == []


@pytest.mark.django_db
def test_search_endpoint_returns_envelope(anon_client, thread):
    response = anon_client.get("/api/search/?q=docker")

    assert response.status_code == 200, response.data
    assert response.data["data"] == []
    assert response.data["meta"]["query"] == "docker"


@pytest.mark.django_db
def test_suggest_endpoint(anon_client, thread):
    response = anon_client.get("/api/search/suggest/?q=настроить")

    assert response.status_code == 200, response.data
    assert response.data["data"][0]["type"] == "thread"


@pytest.mark.django_db
def test_reindex_requires_moderator(auth_client, mod_client):
    assert auth_client.post("/api/search/reindex/").status_code == 403
    assert mod_client.post("/api/search/reindex/").status_code in (200, 202)


@pytest.mark.django_db
def test_search_health_handles_missing_client(monkeypatch):
    monkeypatch.setattr(service, "get_client", lambda: None)
    assert service.search_health() is False
