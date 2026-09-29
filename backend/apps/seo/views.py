"""Views SEO: метаданные, sitemap, robots.txt, OG-изображения (TECHSPEC §4.11, §14)."""

from django.conf import settings
from django.contrib.sitemaps.views import x_robots_tag
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from shared.permissions import IsModerator

from .models import SEOMeta


class SEOMetaSerializer(serializers.ModelSerializer):
    class Meta:
        model = SEOMeta
        fields = ["id", "path", "title", "description", "keywords", "og_image",
                  "canonical", "robots", "is_active", "priority", "updated_at"]
        read_only_fields = ["id", "updated_at"]


class SEOMetaViewSet(viewsets.ModelViewSet):
    """``/api/seo/meta/`` — управление SEO-записями (TECHSPEC §4.11)."""

    queryset = SEOMeta.objects.all()
    serializer_class = SEOMetaSerializer
    permission_classes = [IsModerator]
    search_fields = ["path", "title"]
    ordering = ["-priority", "path"]
    pagination_class = None


class SEOResolveView(APIView):
    """``GET /api/seo/resolve/?path=/t/slug`` — метаданные для рендера (TECHSPEC §4.11)."""

    permission_classes = [AllowAny]

    def get(self, request):
        path = (request.query_params.get("path") or "/").strip()
        record = SEOMeta.for_path(path)
        if record is None:
            return Response({"data": None, "meta": {}, "errors": []},
                            status=status.HTTP_404_NOT_FOUND)
        return Response({"data": SEOMetaSerializer(record).data, "meta": {}, "errors": []})


# ── robots.txt и sitemap (TECHSPEC §14) ──────────────────────────────
def _absolute(path: str) -> str:
    host = settings.SITE_HOST.rstrip("/")
    return f"{host}/{path.lstrip('/')}"


class RobotsTxtView(APIView):
    """``GET /robots.txt``."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        host = settings.SITE_HOST.rstrip("/")
        lines = [
            "User-agent: *",
            "Disallow: /admin/",
            "Disallow: /api/",
            "Disallow: /settings/",
            "Disallow: /moderation/",
            "Allow: /",
            "",
            f"Sitemap: {host}/sitemap.xml",
        ]
        return HttpResponse("\n".join(lines), content_type="text/plain; charset=utf-8")


class ForumSitemap(APIView):
    """``GET /sitemap-forums.xml`` (TECHSPEC §14)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        return _sitemap_xml([
            {
                "loc": _absolute(f"/f/{item.slug}"),
                "lastmod": item.updated_at,
                "changefreq": "daily",
                "priority": "0.8",
            }
            for item in _visible_forums()
        ])


class ThreadSitemap(APIView):
    """``GET /sitemap-threads.xml`` (TECHSPEC §14)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        from apps.threads.models import Thread

        queryset = Thread.objects.filter(is_deleted=False, is_draft=False).order_by(
            "-last_activity_at"
        )[:5000]
        return _sitemap_xml([
            {
                "loc": _absolute(f"/t/{item.slug}"),
                "lastmod": item.last_activity_at or item.updated_at,
                "changefreq": "weekly",
                "priority": "0.6",
            }
            for item in queryset
        ])


class UserSitemap(APIView):
    """``GET /sitemap-users.xml`` (TECHSPEC §14)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        from apps.accounts.models import User

        queryset = (User.objects.filter(is_deleted=False, is_active=True)
                    .only("username", "date_joined", "updated_at")[:5000])
        return _sitemap_xml([
            {"loc": _absolute(f"/u/{item.username}"), "lastmod": item.date_joined,
             "changefreq": "monthly", "priority": "0.3"}
            for item in queryset
        ])


def _visible_forums():
    from apps.forums.models import Forum

    return Forum.objects.all().order_by("order", "name")


def _sitemap_xml(entries: list[dict]) -> HttpResponse:
    """Собрать sitemap XML (TECHSPEC §14)."""
    from io import StringIO

    from django.utils.xmlutils import SimplerXMLGenerator

    buffer = StringIO()
    xml = SimplerXMLGenerator(buffer, "urlset")
    xml.startDocument()
    xml.startElement(
        "urlset",
        {"xmlns": "http://www.sitemaps.org/schemas/sitemap/0.9",
         "xmlns:xhtml": "http://www.w3.org/1999/xhtml"},
    )
    for entry in entries:
        xml.startElement("url", {})
        xml.addQuickElement("loc", entry["loc"])
        if lastmod := entry.get("lastmod"):
            stamp = timezone.localtime(lastmod) if timezone.is_aware(lastmod) else lastmod
            xml.addQuickElement("lastmod", stamp.isoformat())
        if freq := entry.get("changefreq"):
            xml.addQuickElement("changefreq", freq)
        if priority := entry.get("priority"):
            xml.addQuickElement("priority", priority)
        xml.endElement("url")
    xml.endElement("urlset")
    xml.endDocument()
    return HttpResponse(buffer.getvalue(), content_type="application/xml; charset=utf-8")


class SitemapIndex:
    """``GET /sitemap.xml`` — индекс sitemap-файлов (TECHSPEC §14)."""

    #: Имя файла → раздел сайта
    SECTIONS = {
        "forums": "forums",
        "threads": "threads",
        "users": "users",
        "meta": "meta",
    }

    @x_robots_tag
    def __call__(self, request, *args, **kwargs) -> HttpResponse:
        from io import StringIO

        from django.utils.xmlutils import SimplerXMLGenerator

        buffer = StringIO()
        xml = SimplerXMLGenerator(buffer, "sitemapindex")
        xml.startDocument()
        xml.startElement("sitemapindex",
                         {"xmlns": "http://www.sitemaps.org/schemas/sitemap/0.9"})
        stamp = timezone.now()
        for name in self.SECTIONS:
            xml.startElement("sitemap", {})
            xml.addQuickElement("loc", _absolute(f"/sitemap-{name}.xml"))
            xml.addQuickElement("lastmod", stamp.isoformat())
            xml.endElement("sitemap")
        xml.endElement("sitemapindex")
        xml.endDocument()
        return HttpResponse(buffer.getvalue(), content_type="application/xml; charset=utf-8")


SitemapIndexView = SitemapIndex()
