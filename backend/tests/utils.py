"""Помощники для тестов API (TECHSPEC §16)."""

import json

from rest_framework.test import APIClient


class EnvelopeAPIClient(APIClient):
    """APIClient, у которого ``response.data`` соответствует реальному JSON.

    DRF по умолчанию отдаёт в ``response.data`` данные *до* рендеринга, поэтому
    конверт ``{data, meta, errors}`` не виден. Здесь он парсится из тела ответа —
    тесты проверяют ровно то, что увидит клиент.
    """

    def request(self, **kwargs):
        response = super().request(**kwargs)
        content_type = response.get("Content-Type", "")
        if content_type.startswith("application/json") and response.content:
            try:
                response.data = json.loads(response.content)
            except (ValueError, UnicodeDecodeError):  # pragma: no cover
                pass
        return response


def payload(response) -> dict:
    """``data`` из конверта ответа."""
    return response.data["data"]


def errors(response) -> list:
    """``errors`` из конверта ответа."""
    return response.data.get("errors") or []


def field_errors(response, field: str) -> list:
    """Ошибки, относящиеся к конкретному полю."""
    return [e for e in errors(response) if e.get("field") == field]
