"""Health-check и метрики (TECHSPEC §5.3, §17.8)."""

import time

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

START_TIME = time.monotonic()

from .metrics import observe_request, registry  # noqa: E402
from .renderers import EnvelopeJSONRenderer  # noqa: E402


def _check_database() -> str:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return "ok"
    except Exception:
        return "error"


def _check_redis() -> str:
    try:
        cache.set("health:probe", "1", timeout=5)
        return "ok" if cache.get("health:probe") == "1" else "error"
    except Exception:
        return "error"


def _check_kafka() -> str:
    if not getattr(settings, "KAFKA_ENABLED", False):
        return "disabled"
    try:
        from events.producer import producer_health

        return "ok" if producer_health() else "error"
    except Exception:
        return "error"


def _check_elasticsearch() -> str:
    if not getattr(settings, "ELASTIC_ENABLED", True):
        return "disabled"
    try:
        from apps.search.service import search_health

        return "ok" if search_health() else "error"
    except Exception:
        return "error"


def _check_storage() -> str:
    try:
        from django.core.files.storage import default_storage

        default_storage.exists("health.probe")
        return "ok"
    except Exception:
        return "error"


def _check_celery() -> str:
    try:
        from config.celery import app as celery_app

        inspector = celery_app.control.inspect(timeout=1.0)
        ping = inspector.ping()
        return "ok" if ping else "unavailable"
    except Exception:
        return "unavailable"


CHECKS = {
    "database": _check_database,
    "redis": _check_redis,
    "kafka": _check_kafka,
    "elasticsearch": _check_elasticsearch,
    "storage": _check_storage,
    "celery": _check_celery,
}


class HealthView(APIView):
    """``GET /api/health/`` — состояние всех зависимостей (TECHSPEC §5.3)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    renderer_classes = [EnvelopeJSONRenderer]

    def get(self, request):
        services = {}
        for name, check in CHECKS.items():
            services[name] = check()

        degraded = [k for k, v in services.items() if v == "error"]
        critical = [k for k in degraded if k in ("database", "redis")]
        if critical:
            status = "error"
        elif degraded:
            status = "degraded"
        else:
            status = "ok"

        payload = {
            "status": status,
            "services": services,
            "version": getattr(settings, "APP_VERSION", "0.0.0"),
            "uptime_seconds": int(time.monotonic() - START_TIME),
            "timestamp": timezone.now().isoformat(),
        }
        code = 200 if status != "error" else 503
        return Response({"data": payload, "meta": {}, "errors": []}, status=code)


class MetricsView(APIView):
    """``GET /api/metrics/`` — метрики в формате Prometheus."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        return Response(
            {"data": registry.render(), "meta": {}, "errors": []},
            content_type="text/plain; version=0.0.4",
        )


class MetricsMiddleware:
    """Собирает метрики длительности запросов (TECHSPEC §17.8)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.perf_counter()
        response = self.get_response(request)
        duration = time.perf_counter() - start
        if request.path.startswith("/api/"):
            observe_request(
                _route_template(request),
                request.method,
                response.status_code,
                duration,
            )
        return response


def _route_template(request) -> str:
    """Шаблон маршрута вместо полного пути — чтобы не плодить кардинальность."""
    resolver = getattr(request, "resolver_match", None)
    route = getattr(resolver, "route", None)
    if route:
        return "/" + route.strip("/")
    return "/".join(request.path.split("/")[:3])
