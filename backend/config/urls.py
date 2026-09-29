"""Корневой URLconf ForumOS (TECHSPEC §11)."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from apps.accounts.views import (
    EmailVerificationView,
    LoginView,
    LogoutView,
    PasswordResetConfirmView,
    PasswordResetView,
    RefreshTokenView,
    RegisterView,
    ResendVerificationView,
)
from apps.accounts.views_profile import UserStatsView, UserViewSet
from apps.analytics.views import (
    AdminStatsView,
    EventIngestView,
    ProfileHeatmapView,
)
from apps.analytics.views import (
    UserStatsView as AnalyticsUserStatsView,
)
from apps.forums.views import ForumViewSet
from apps.moderation.views import (
    AuditLogViewSet,
    FlagViewSet,
    ModerationContentView,
    ModerationUserViewSet,
)
from apps.notifications.views import NotificationViewSet
from apps.posts.views import PostViewSet
from apps.reactions.views import ReactionViewSet
from apps.search.views import ReindexView, SearchView, SuggestView
from apps.seo.og import OGImageView
from apps.seo.views import (
    ForumSitemap,
    RobotsTxtView,
    SEOMetaViewSet,
    SEOResolveView,
    SitemapIndexView,
    ThreadSitemap,
    UserSitemap,
)
from apps.threads.views import ThreadPostsViewSet, ThreadViewSet
from shared.health import HealthView, MetricsView

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")
router.register("forums", ForumViewSet, basename="forum")
router.register("threads", ThreadViewSet, basename="thread")
router.register("posts", PostViewSet, basename="post")
router.register("reactions", ReactionViewSet, basename="reaction")
router.register("notifications", NotificationViewSet, basename="notification")
router.register("moderation/flags", FlagViewSet, basename="flag")
router.register("moderation/users", ModerationUserViewSet, basename="moderation-user")
router.register("moderation/audit-log", AuditLogViewSet, basename="audit-log")
router.register("seo/meta", SEOMetaViewSet, basename="seo-meta")

moderation_content_patterns = [
    path("api/moderation/posts/<int:pk>/hide/",
         ModerationContentView.as_view({"post": "hide_post"}),
         name="moderation-post-hide"),
    path("api/moderation/threads/<int:pk>/hide/",
         ModerationContentView.as_view({"post": "hide_thread"}),
         name="moderation-thread-hide"),
]
auth_patterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("refresh/", RefreshTokenView.as_view(), name="auth-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("password/reset/", PasswordResetView.as_view(), name="auth-password-reset"),
    path("password/confirm/", PasswordResetConfirmView.as_view(), name="auth-password-confirm"),
    path("verify-email/", EmailVerificationView.as_view(), name="auth-verify-email"),
    path("resend-verification/", ResendVerificationView.as_view(), name="auth-resend-verification"),
]

urlpatterns = [
    # ── Ресурсы API (TECHSPEC §11) ───────────────────────────────
    path("api/", include(router.urls)),
    # Посты внутри темы: вложенные маршруты, а не отдельный ресурс
    path("api/threads/<slug:slug>/posts/",
         ThreadPostsViewSet.as_view({"get": "list", "post": "create"}),
         name="thread-posts"),
    # Скрытие контента модератором
    path("", include(moderation_content_patterns)),
    # ── Аутентификация (TECHSPEC §11.1) ──────────────────────────
    path("api/auth/", include((auth_patterns, "auth"))),
    # ── Прочее API ──────────────────────────────────────────────
    path("api/stats/", UserStatsView.as_view(), name="stats"),
    path("api/search/", SearchView.as_view(), name="search"),
    path("api/search/suggest/", SuggestView.as_view(), name="search-suggest"),
    path("api/search/reindex/", ReindexView.as_view(), name="search-reindex"),
    path("api/analytics/events/", EventIngestView.as_view(), name="analytics-events"),
    path("api/analytics/heatmap/", ProfileHeatmapView.as_view(), name="analytics-heatmap"),
    path("api/analytics/users/<int:pk>/stats/", AnalyticsUserStatsView.as_view(),
         name="analytics-user-stats"),
    path("api/analytics/stats/", AdminStatsView.as_view(), name="analytics-stats"),
    path("api/seo/resolve/", SEOResolveView.as_view(), name="seo-resolve"),
    path("api/health/", HealthView.as_view(), name="health"),
    path("api/metrics/", MetricsView.as_view(), name="metrics"),
    # ── SEO (TECHSPEC §14) ──────────────────────────────────────
    path("robots.txt", RobotsTxtView.as_view(), name="robots"),
    path("sitemap.xml", SitemapIndexView, name="sitemap-index"),
    path("sitemap-threads.xml", ThreadSitemap.as_view(), name="sitemap-threads"),
    path("sitemap-forums.xml", ForumSitemap.as_view(), name="sitemap-forums"),
    path("sitemap-users.xml", UserSitemap.as_view(), name="sitemap-users"),
    path("og/thread/<slug:slug>.png",
         OGImageView.as_view(kind="thread"), name="og-thread"),
    path("og/forum/<slug:slug>.png",
         OGImageView.as_view(kind="forum"), name="og-forum"),
    path("og/user/<str:slug>.png",
         OGImageView.as_view(kind="user"), name="og-user"),
    # ── OpenAPI (TECHSPEC §11.1) ────────────────────────────────
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    # ── Django admin ────────────────────────────────────────────
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
