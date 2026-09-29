"""Пагинация ForumOS: cursor-based (TECHSPEC §11.1)."""

from rest_framework.pagination import CursorPagination as BaseCursorPagination
from rest_framework.response import Response


class CursorPagination(BaseCursorPagination):
    """Курсорная пагинация с метаданными в формате ТЗ.

    Запрос:  ``?cursor=<opaque>&limit=20``
    Ответ:   ``meta.next_cursor``, ``meta.previous_cursor``, ``meta.limit``
    """

    page_size = 20
    page_size_query_param = "limit"
    max_page_size = 100
    ordering = "-created_at"

    def get_paginated_response(self, data):
        """Ответ в конверте API (TECHSPEC §11.1).

        ``{data: [...], meta: {next_cursor, previous_cursor, limit, count}, errors: []}``
        """
        return Response(
            {
                "data": data,
                "meta": {
                    "next_cursor": self.get_next_cursor(),
                    "previous_cursor": self.get_previous_cursor(),
                    "limit": self.page_size,
                    "has_next": self.has_next,
                    "count": getattr(self, "count", None),
                },
                "errors": [],
            }
        )

    def get_next_cursor(self):
        """Следующий курсор (из DRF-логики), готовый для передачи клиенту."""
        next_url = self.get_next_link()
        if not next_url:
            return None
        return self._cursor_from_url(next_url)

    def get_previous_cursor(self):
        previous_url = self.get_previous_link()
        if not previous_url:
            return None
        return self._cursor_from_url(previous_url)

    @staticmethod
    def _cursor_from_url(url):
        from urllib.parse import parse_qs, urlparse

        query = parse_qs(urlparse(url).query)
        return query.get("cursor", [None])[0]

    def paginate_queryset(self, queryset, request, view=None):
        self.request = request
        self.count = self._safe_count(queryset)
        return super().paginate_queryset(queryset, request, view=view)

    def _safe_count(self, queryset):
        """Количество считается только когда явно запрошено (?with_count=1).

        Подсчёт на больших лентах дорог, поэтому по умолчанию возвращается None
        и клиент ориентируется на курсоры (TECHSPEC §5.1).
        """
        request = self.request
        if request is None or request.query_params.get("with_count") not in ("1", "true"):
            return None
        try:
            return queryset.count()
        except (AttributeError, TypeError):  # pragma: no cover - не queryset
            return None
