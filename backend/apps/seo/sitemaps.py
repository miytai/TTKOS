"""SEO-сигналы и sitemap (TECHSPEC §4.11)."""

from django.contrib.sitemaps import Sitemap

from .models import SEOMeta


class _BaseSitemap(Sitemap):
    """Общий хелпер: абсолютный URL и свежий ``lastmod``."""

    def _absolute(self, path: str) -> str:
        from django.conf import settings

        return f"{settings.SITE_HOST.rstrip('/')}/{path.lstrip('/')}"

    def lastmod(self, item):  # pragma: no cover - переопределяется наследниками
        return getattr(item, "updated_at", None)


class ForumSitemap(_BaseSitemap):
    """Карта разделов (TECHSPEC §14)."""

    changefreq = "daily"
    priority = 0.8

    def items(self):
        from apps.forums.models import Forum

        return Forum.objects.all().order_by("order", "name")

    def location(self, item) -> str:
        return self._absolute(f"/f/{item.slug}")

    def lastmod(self, item):
        return item.updated_at


class ThreadSitemap(_BaseSitemap):
    """Карта опубликованных тем (TECHSPEC §14)."""

    changefreq = "weekly"
    priority = 0.6

    def items(self):
        from apps.threads.models import Thread

        return Thread.objects.filter(is_deleted=False, is_draft=False).order_by(
            "-last_activity_at"
        )[:5000]

    def location(self, item) -> str:
        return self._absolute(f"/t/{item.slug}")

    def lastmod(self, item):
        return item.last_activity_at or item.updated_at


class UserSitemap(_BaseSitemap):
    """Карта профилей (TECHSPEC §14)."""

    changefreq = "monthly"
    priority = 0.3

    def items(self):
        from apps.accounts.models import User

        return User.objects.filter(is_deleted=False, is_active=True).order_by(
            "-date_joined"
        )[:5000]

    def location(self, item) -> str:
        return self._absolute(f"/u/{item.username}")

    def lastmod(self, item):
        return item.date_joined


class SEOMetaSitemap(Sitemap):
    """Карта сайта из таблицы ``seo_meta`` (TECHSPEC §4.11)."""

    changefreq = "daily"
    priority = 0.7

    def items(self):
        return SEOMeta.objects.filter(is_active=True).order_by("-priority", "path")

    def location(self, item) -> str:
        return item.path

    def lastmod(self, item):
        return item.updated_at
