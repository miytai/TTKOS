"""Генерация OG-изображений (TECHSPEC §14).

Рендер картинок без внешних зависимостей: PNG собирается вручную через
Pillow, доступный в контейнере. Если Pillow недоступен — отдаём SVG.
"""

from __future__ import annotations

import html
import io

from django.conf import settings
from django.http import HttpResponse
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

WIDTH, HEIGHT = 1200, 630
PALETTE = ["#141210", "#1c1917", "#7dd3a0", "#f5f0e8", "#a8a29e"]


class OGImageView(APIView):
    """``GET /og/<kind>/<slug>.png`` — превью для репостов (TECHSPEC §14)."""

    kind = "thread"

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request, slug: str) -> HttpResponse:
        kind = self.kind
        title = self._title_for(kind, slug)
        if title is None:
            # Объекта нет — отдаём 404, а не «картинку-заглушку» (TECHSPEC §14).
            from rest_framework import status

            return Response({"data": None, "meta": None,
                             "errors": [{"code": "not_found", "field": None,
                                         "message": "Объект не найден"}]},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:  # pragma: no cover - Pillow не установлен
            return self._svg(title, kind)

        image = Image.new("RGB", (WIDTH, HEIGHT), PALETTE[0])
        draw = ImageDraw.Draw(image)

        # Фон: мягкий градиент в тёмных тонах
        for y in range(HEIGHT):
            ratio = y / HEIGHT
            draw.line(
                [(0, y), (WIDTH, y)],
                fill=_blend(PALETTE[0], PALETTE[1], ratio * 0.8),
            )

        accent = PALETTE[2]
        draw.rounded_rectangle([72, 96, 120, 144], radius=12, fill=accent)
        title_font = self._font(ImageFont, 62)
        meta_font = self._font(ImageFont, 30)
        brand_font = self._font(ImageFont, 34)

        draw.text((160, 104), self._kind_label(kind), font=meta_font, fill=accent)
        for index, line in enumerate(_wrap(title, 26)[:4]):
            draw.text((72, 232 + index * 82), line, font=title_font, fill=PALETTE[3])
        draw.text((72, HEIGHT - 128), settings.SITE_NAME, font=brand_font, fill=PALETTE[4])
        draw.text((72, HEIGHT - 84), f"{settings.SITE_HOST.rstrip('/')}/t/{slug}",
                  font=self._font(ImageFont, 24), fill=PALETTE[4])

        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return HttpResponse(buffer.getvalue(), content_type="image/png")

    @staticmethod
    def _font(font_module, size: int):
        """Загрузить шрифт с запасным вариантом (TECHSPEC §14)."""
        from django.conf import settings as django_settings

        for path in getattr(django_settings, "OG_FONT_PATHS", []):
            try:
                return font_module.truetype(path, size)
            except OSError:
                continue
        try:
            return font_module.load_default(size=size)
        except TypeError:  # pragma: no cover - старый Pillow
            return font_module.load_default()

    @staticmethod
    def _kind_label(kind: str) -> str:
        return {"thread": "ForumOS · Тема", "forum": "ForumOS · Раздел",
                "user": "ForumOS · Профиль"}.get(kind, "ForumOS")

    @staticmethod
    def _title_for(kind: str, slug: str) -> str | None:
        """Заголовок OG-картинки или ``None``, если объекта нет (TECHSPEC §14)."""
        if kind == "thread":
            from apps.threads.models import Thread

            item = Thread.objects.filter(slug=slug, is_deleted=False).only("title").first()
            return item.title if item else None
        if kind == "forum":
            from apps.forums.models import Forum

            item = Forum.objects.filter(slug=slug).only("name").first()
            return item.name if item else None
        from apps.accounts.models import User

        item = User.objects.filter(username=slug, is_deleted=False).only("username").first()
        return item.username if item else None

    def _svg(self, title: str, kind: str) -> HttpResponse:
        """Фолбэк-SVG, если Pillow недоступен."""
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}">'
            f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{PALETTE[0]}"/>'
            f'<text x="72" y="200" fill="{PALETTE[2]}" font-size="32" '
            f'font-family="sans-serif">{html.escape(self._kind_label(kind))}</text>'
            f'<text x="72" y="320" fill="{PALETTE[3]}" font-size="64" '
            f'font-family="sans-serif">'
            f'{html.escape(_wrap(title, 22)[0] if title else "ForumOS")}</text>'
            f'<text x="72" y="540" fill="{PALETTE[4]}" font-size="28" '
            f'font-family="sans-serif">{html.escape(settings.SITE_NAME)}</text>'
            "</svg>"
        )
        return HttpResponse(svg, content_type="image/svg+xml")


def _blend(first: str, second: str, ratio: float) -> tuple[int, int, int]:
    a = _rgb(first)
    b = _rgb(second)
    return tuple(int(a[i] + (b[i] - a[i]) * ratio) for i in range(3))


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _wrap(text: str, width: int) -> list[str]:
    words = (text or "").split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]
