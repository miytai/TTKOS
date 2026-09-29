"""Сервис полнотекстового поиска на Elasticsearch (TECHSPEC §4.7)."""

from datetime import date, datetime, timedelta

from django.conf import settings

from shared.logging import get_logger

logger = get_logger("forumos.search")

_client = None


def get_client():
    """Ленивая инициализация клиента Elasticsearch."""
    global _client
    if _client is not None:
        return _client
    if not getattr(settings, "ELASTIC_ENABLED", True):
        return None
    try:
        from elasticsearch import Elasticsearch
    except ImportError:  # pragma: no cover
        logger.warning("elasticsearch_package_missing")
        return None

    username = getattr(settings, "ELASTIC_USERNAME", "")
    password = getattr(settings, "ELASTIC_PASSWORD", "")
    auth = (username, password) if username and password else None

    _client = Elasticsearch(
        settings.ELASTIC_URL,
        basic_auth=auth,
        request_timeout=getattr(settings, "ELASTIC_TIMEOUT", 5),
        retry_on_timeout=True,
        max_retries=2,
    )
    return _client


def search_health() -> bool:
    """Проверка доступности Elasticsearch для health-check."""
    client = get_client()
    if client is None:
        return False
    try:
        return bool(client.ping())
    except Exception:  # pragma: no cover - се��вис недоступен
        return False


def index_name(entity: str) -> str:
    return f"{settings.ELASTIC_INDEX_PREFIX}-{entity}"


# ── Маппинги индексов (TECHSPEC §4.7) ───────────────────────────────
THREAD_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "analysis": {"analyzer": {"ru_analyzer": {"type": "custom",
                                                 "tokenizer": "standard",
                                                 "filter": ["lowercase", "stop"]}}},
    },
    "mappings": {
        "properties": {
            "id": {"type": "integer"},
            "slug": {"type": "keyword"},
            "title": {"type": "text", "analyzer": "ru_analyzer",
                      "fields": {"raw": {"type": "keyword"}}},
            "body": {"type": "text", "analyzer": "ru_analyzer"},
            "tags": {"type": "keyword"},
            "author_username": {"type": "keyword"},
            "forum_slug": {"type": "keyword"},
            "reactions_count": {"type": "integer"},
            "posts_count": {"type": "integer"},
            "created_at": {"type": "date"},
            "last_activity_at": {"type": "date"},
        }
    },
}

POST_MAPPING = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "id": {"type": "integer"},
            "thread_id": {"type": "integer"},
            "thread_slug": {"type": "keyword"},
            "thread_title": {"type": "text"},
            "body": {"type": "text"},
            "author_username": {"type": "keyword"},
            "forum_slug": {"type": "keyword"},
            "created_at": {"type": "date"},
        }
    },
}

USER_MAPPING = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "id": {"type": "integer"},
            "username": {"type": "keyword"},
            "bio": {"type": "text"},
            "reputation": {"type": "integer"},
            "rank": {"type": "keyword"},
            "created_at": {"type": "date"},
        }
    },
}

MAPPINGS = {"threads": THREAD_MAPPING, "posts": POST_MAPPING, "users": USER_MAPPING}


def ensure_indices() -> list[str]:
    """Создать индексы, если их ещё нет (идемпотентно)."""
    client = get_client()
    if client is None:
        return []

    created = []
    for entity, body in MAPPINGS.items():
        name = index_name(entity)
        try:
            if not client.indices.exists(index=name):
                client.indices.create(index=name, **body)
                created.append(name)
        except Exception as exc:  # pragma: no cover - се��вис недоступен
            logger.warning("elastic_index_create_failed", index=name, error=str(exc)[:200])
    if created:
        logger.info("elastic_indices_created", indices=created)
    return created


def index_document(entity: str, doc_id: int, document: dict, refresh: bool = False) -> bool:
    """Проиндексировать документ."""
    client = get_client()
    if client is None:
        return False
    try:
        client.index(index=index_name(entity), id=doc_id, document=document, refresh=refresh)
        return True
    except Exception as exc:  # pragma: no cover
        logger.warning("elastic_index_failed", entity=entity, doc_id=doc_id, error=str(exc)[:200])
        return False


def delete_document(entity: str, doc_id: int) -> bool:
    client = get_client()
    if client is None:
        return False
    try:
        client.delete(index=index_name(entity), id=doc_id, refresh=False, ignore=[404])
        return True
    except Exception as exc:  # pragma: no cover
        logger.warning("elastic_delete_failed", entity=entity, doc_id=doc_id, error=str(exc)[:200])
        return False


def refresh_indices() -> None:
    """Сделать документы видимыми сразу после reindex."""
    client = get_client()
    if client is None:
        return
    for entity in MAPPINGS:
        try:
            client.indices.refresh(index=index_name(entity))
        except Exception:  # pragma: no cover
            pass


# ── Документы (TECHSPEC §4.7) ───────────────────────────────────────
def thread_document(thread) -> dict:
    return {
        "id": thread.pk,
        "slug": thread.slug,
        "title": thread.title,
        "body": thread.body[:20_000],
        "tags": list(thread.tags.values_list("slug", flat=True)),
        "author_username": thread.author_display,
        "forum_slug": thread.forum.slug,
        "reactions_count": thread.reactions_count,
        "posts_count": thread.posts_count,
        "created_at": thread.created_at.isoformat(),
        "last_activity_at": thread.last_activity_at.isoformat(),
    }


def post_document(post) -> dict:
    return {
        "id": post.pk,
        "thread_id": post.thread_id,
        "thread_slug": post.thread.slug,
        "thread_title": post.thread.title,
        "body": post.body[:20_000],
        "author_username": post.author_display,
        "forum_slug": post.thread.forum.slug,
        "created_at": post.created_at.isoformat(),
    }


def user_document(user) -> dict:
    profile = getattr(user, "userprofile", None)
    return {
        "id": user.pk,
        "username": user.username,
        "bio": getattr(profile, "bio", ""),
        "reputation": getattr(profile, "reputation", 0),
        "rank": getattr(profile, "rank", "newbie"),
        "created_at": user.date_joined.isoformat(),
    }


# ── Поиск (TECHSPEC §4.7) ───────────────────────────────────────────
SORTS = {
    "relevance": ["_score", {"last_activity_at": "desc"}],
    "newest": [{"created_at": "desc"}],
    "popular": [{"reactions_count": "desc"}, {"posts_count": "desc"}],
}

HIGHLIGHT = {
    "pre_tags": ["<mark>"],
    "post_tags": ["</mark>"],
    "fields": {"title": {}, "body": {"fragment_size": 180, "number_of_fragments": 1}},
}


def _filters(filters: dict) -> list[dict]:
    clauses: list[dict] = []
    mapping = {
        "forum": ("forum_slug", "forum"),
        "tag": ("tags", "tag"),
        "author": ("author_username", "author"),
    }
    for _key, (field, param) in mapping.items():
        value = filters.get(param)
        if value:
            clauses.append({"term": {field: value.lower() if field != "author" else value}})
    date_from = filters.get("from")
    date_to = filters.get("to")
    if date_from:
        clauses.append({"range": {"created_at": {"gte": _iso(date_from)}}})
    if date_to:
        clauses.append({"range": {"created_at": {"lte": _iso(date_to)}}})
    return [{"bool": {"filter": clauses}}] if clauses else []


def _iso(value) -> str:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def search(entity: str, query: str, *, filters: dict | None = None,
           ordering: str = "relevance", limit: int = 20, offset: int = 0,
           highlight: bool = True) -> dict:
    """Выполнить поиск по индексу сущности."""
    client = get_client()
    empty = {"total": 0, "results": []}
    if client is None or not query:
        return empty

    body = {
        "query": {
            "bool": {
                "must": [
                    {"multi_match": {
                        "query": query,
                        "fields": ["title^3", "body", "thread_title", "username", "bio"],
                        "type": "best_fields",
                        "fuzziness": "AUTO",
                    }}
                ],
                "filter": _filters(filters or {}),
            }
        },
        "from": offset,
        "size": limit,
        "sort": SORTS.get(ordering, SORTS["relevance"]),
    }
    if highlight and entity in ("threads", "posts"):
        body["highlight"] = HIGHLIGHT

    try:
        response = client.search(index=index_name(entity), body=body)
    except Exception as exc:  # pragma: no cover
        logger.warning("elastic_search_failed", entity=entity, error=str(exc)[:200])
        return empty

    hits = response.get("hits", {})
    total = hits.get("total", {})
    total_value = total.get("value", 0) if isinstance(total, dict) else total

    results = []
    for hit in hits.get("hits", []):
        source = hit.get("_source", {})
        results.append({
            "id": source.get("id") or hit.get("_id"),
            "score": hit.get("_score"),
            "entity": entity,
            "title": source.get("title") or source.get("thread_title") or source.get("username"),
            "snippet": _snippet(hit, source),
            "author_username": source.get("author_username") or source.get("username"),
            "forum_slug": source.get("forum_slug"),
            "tags": source.get("tags", []),
            "thread_slug": source.get("thread_slug") or source.get("slug"),
            "url": _url_for(entity, source),
            "created_at": source.get("created_at"),
            "reactions_count": source.get("reactions_count", 0),
        })

    return {"total": total_value, "results": results}


def _plain(text: str | None, limit: int) -> str:
    from shared.markdown import extract_text_preview

    return extract_text_preview(text or "", limit)


def _snippet(hit: dict, source: dict) -> str:
    """Сниппет с подсветкой из Elasticsearch (TECHSPEC §4.7)."""
    highlight = hit.get("highlight") or {}
    fragments: list[str] = []
    for field in ("title", "body", "thread_title"):
        value = highlight.get(field)
        if isinstance(value, str):
            fragments.append(value)
        elif isinstance(value, list):
            fragments.extend(str(item) for item in value)
    if fragments:
        return " … ".join(fragments)[:400]
    return _plain(source.get("body") or source.get("bio"), 180)


def _url_for(entity: str, source: dict) -> str:
    if entity == "threads":
        return f"/t/{source.get('slug')}"
    if entity == "posts":
        return f"/t/{source.get('thread_slug')}#post-{source.get('id')}"
    return f"/u/{source.get('username')}"


def autocomplete(query: str, limit: int = 8) -> list[dict]:
    """Автодополнение: популярные темы и теги (TECHSPEC §4.7)."""
    if not query or len(query) < 2:
        return []
    from apps.threads.models import Tag, Thread

    threads = list(
        Thread.objects.filter(title__icontains=query, is_deleted=False)
        .order_by("-last_activity_at")
        .values("title", "slug")[:limit]
    )
    tags = list(
        Tag.objects.filter(name__icontains=query).order_by("-usage_count")
        .values("name", "slug")[:limit]
    )
    suggestions = [{"type": "thread", "label": item["title"], "value": f"/t/{item['slug']}"}
                   for item in threads]
    suggestions += [{"type": "tag", "label": f"#{item['name']}", "value": f"/?tag={item['slug']}"}
                    for item in tags]
    return suggestions[:limit]


def purge_old_documents(days: int = 30) -> int:
    """Удалить проиндексированные удалённые объекты (TECHSPEC §5.3)."""
    client = get_client()
    if client is None:
        return 0
    cutoff = (datetime.now(tz=None) - timedelta(days=days)).isoformat()
    deleted = 0
    for entity, field in (("threads", "created_at"), ("posts", "created_at")):
        try:
            response = client.delete_by_query(
                index=index_name(entity),
                body={"query": {"range": {field: {"lt": cutoff}}}},
                refresh=False,
                ignore_unavailable=True,
            )
            deleted += response.get("deleted", 0)
        except Exception as exc:  # pragma: no cover
            logger.warning("elastic_purge_failed", entity=entity, error=str(exc)[:200])
    return deleted
