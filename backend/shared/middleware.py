"""Middleware ForumOS (TECHSPEC §5.8: request_id в каждом логе)."""

import time
import uuid

from .logging import get_logger

logger = get_logger("forumos.http")


class RequestIdMiddleware:
    """Добавляет X-Request-Id в запрос и ответ, кладёт id в structlog-контекст."""

    header = "HTTP_X_REQUEST_ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        import structlog

        request_id = request.META.get(self.header) or uuid.uuid4().hex
        request.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        request._forumos_start = time.perf_counter()
        try:
            response = self.get_response(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response["X-Request-Id"] = request_id
        return response


class AccessLogMiddleware:
    """JSON-лог каждого запроса: метод, путь, статус, длительность."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.perf_counter()
        response = self.get_response(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        level = "info"
        if response.status_code >= 500:
            level = "error"
        elif response.status_code >= 400:
            level = "warning"

        logger.info(
            "http_request",
            method=request.method,
            path=request.get_full_path()[:512],
            status=response.status_code,
            duration_ms=duration_ms,
            user_id=getattr(request, "user_id", None),
            level=level,
        )
        return response
