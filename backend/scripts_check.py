"""Проверка импорта и конфигурации Django (без БД)."""

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from django.core.checks import run_checks  # noqa: E402
from django.urls import reverse  # noqa: E402

import config.urls  # noqa: E402,F401
import config.asgi  # noqa: E402,F401

errors = run_checks()
if errors:
    for error in errors:
        sys.stdout.write(f"CHECK ERROR: {error}\n")
    raise SystemExit(1)

for name in ("schema", "health", "search", "auth:auth-login", "forum-list",
             "thread-list", "notification-list", "flag-list", "user-list",
             "moderation-post-hide-post", "analytics-events", "seo-meta-list",
             "search-suggest", "sitemap-index", "robots", "og-user"):
    try:
        reverse(name)
        sys.stdout.write(f"OK url {name}\n")
    except Exception as exc:  # noqa: BLE001
        sys.stdout.write(f"FAIL url {name}: {exc}\n")

sys.stdout.write("OK django checks and imports\n")
