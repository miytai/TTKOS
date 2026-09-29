"""Views поиска (TECHSPEC §4.7)."""

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import service


class SearchView(APIView):
    """``GET /api/search/`` — полнотекстовый поиск (TECHSPEC §4.7)."""

    permission_classes = [AllowAny]
    throttle_scope = "search"

    def get(self, request):
        query = (request.query_params.get("q") or "").strip()
        limit = _int_param(request, "limit", 20, 1, 50)
        page = _int_param(request, "page", 1, 1, 1000)

        result = service.search(
            entity="threads",
            query=query,
            filters={k: v for k, v in request.query_params.items()
                     if k in ("forum", "tag", "author", "from", "to")},
            ordering=request.query_params.get("ordering", "relevance"),
            limit=limit,
            offset=(page - 1) * limit,
        )
        return Response({
            "data": result["results"],
            "meta": {"query": query, "total": result["total"], "page": page,
                     "limit": limit, "pages": _pages(result["total"], limit)},
            "errors": [],
        })


class SuggestView(APIView):
    """``GET /api/search/suggest/`` — автодополнение (TECHSPEC §4.7)."""

    permission_classes = [AllowAny]
    throttle_scope = "search"

    def get(self, request):
        query = (request.query_params.get("q") or "").strip()
        limit = _int_param(request, "limit", 8, 1, 20)
        return Response({"data": service.autocomplete(query, limit=limit),
                         "meta": {}, "errors": []})


class ReindexView(APIView):
    """``POST /api/search/reindex/`` — перестроение индексов (TECHSPEC §5.3)."""

    def get_permissions(self):
        from shared.permissions import IsModerator

        return [IsModerator()]

    def post(self, request):
        from apps.search.tasks import reindex_all

        task = reindex_all.delay()
        return Response({"data": {"task_id": task.id}, "meta": {}, "errors": []},
                        status=status.HTTP_202_ACCEPTED)


def _int_param(request, name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(request.query_params.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


def _pages(total: int, limit: int) -> int:
    if not limit:
        return 0
    return (total + limit - 1) // limit
