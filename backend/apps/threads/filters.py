"""Фильтры лент (TECHSPEC §4.3, §4.4, §11.1)."""

import django_filters as filters
from django.db.models import Q

from .models import Thread


class ThreadFilter(filters.FilterSet):
    """Фильтры списка тем: раздел, теги, автор, даты, статусы (TECHSPEC §4.3)."""

    forum = filters.CharFilter(field_name="forum__slug", lookup_expr="iexact")
    author = filters.CharFilter(field_name="author__username", lookup_expr="iexact")
    tag = filters.CharFilter(method="filter_tag")
    tags = filters.CharFilter(method="filter_tags")
    pinned = filters.BooleanFilter(field_name="is_pinned")
    locked = filters.BooleanFilter(field_name="is_locked")
    draft = filters.BooleanFilter(field_name="is_draft")
    date_from = filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    date_to = filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")
    activity_from = filters.DateTimeFilter(field_name="last_activity_at", lookup_expr="gte")
    activity_to = filters.DateTimeFilter(field_name="last_activity_at", lookup_expr="lte")
    subscribed = filters.BooleanFilter(method="filter_subscribed")

    class Meta:
        model = Thread
        fields = ["is_pinned", "is_locked", "is_draft"]

    def filter_tag(self, queryset, name, value):
        return queryset.filter(tags__slug=value.lower()).distinct()

    def filter_tags(self, queryset, name, value):
        slugs = [s.strip().lower() for s in value.split(",") if s.strip()]
        if not slugs:
            return queryset
        for slug in slugs:
            queryset = queryset.filter(tags__slug=slug)
        return queryset.distinct()

    def filter_subscribed(self, queryset, name, value):
        user = getattr(self.request, "user", None)
        if not value or user is None or not user.is_authenticated:
            return queryset
        return queryset.filter(subscriptions__user=user)

    @property
    def qs(self):
        queryset = super().qs
        user = getattr(getattr(self, "request", None), "user", None)
        if user is not None and user.is_authenticated and not user.is_staff:
            queryset = queryset.filter(is_draft=False).filter(
                Q(is_deleted=False) | Q(author=user)
            )
        return queryset.filter(is_deleted=False)


class PostFilter(filters.FilterSet):
    """Фильтры постов треда."""

    author = filters.CharFilter(field_name="author__username", lookup_expr="iexact")
    date_from = filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    date_to = filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")
    has_attachments = filters.BooleanFilter(method="filter_has_attachments")

    class Meta:
        fields = ["is_edited", "author"]

    def filter_has_attachments(self, queryset, name, value):
        if value is None:
            return queryset
        return queryset.filter(attachments__isnull=not value).distinct()
