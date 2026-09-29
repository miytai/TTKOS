"""Единый обработчик исключений API (TECHSPEC §11.1).

Формат ошибки:

    {
      "data": null,
      "meta": null,
      "errors": [{"code": "validation_error", "field": "email", "message": "..."}]
    }
"""

import re

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .logging import get_logger

logger = get_logger("forumos.api")


def _flatten(detail, prefix=""):
    """Преобразовать DRF-ошибку в плоский список {field, message}.

    Индексы списков отбрасываются: для клиента поле — это имя входного
    параметра (``password``, а не ``password[0]``).
    """
    errors: list[dict] = []

    if isinstance(detail, dict):
        for field, value in detail.items():
            field_name = f"{prefix}.{field}" if prefix else str(field)
            errors.extend(_flatten(value, prefix=field_name))
    elif isinstance(detail, list):
        # Несколько сообщений по одному полю склеиваем в одно
        messages = [str(item) for item in detail if not isinstance(item, dict | list)]
        if messages and prefix:
            return [{"code": "validation_error", "field": _strip_index(prefix),
                     "message": "; ".join(messages)}]
        for value in detail:
            errors.extend(_flatten(value, prefix=prefix))
    else:
        message = str(detail)
        errors.append(
            {
                "code": "validation_error" if prefix else "error",
                "field": _strip_index(prefix) or None,
                "message": message,
            }
        )
    return errors


def _strip_index(field: str) -> str:
    """Убрать ``[0]``/``[1]`` из имени поля."""
    return re.sub(r"\[\d+\]", "", field)


def api_exception_handler(exc, context):
    """Обернуть любое исключение в формат конверта API."""
    if isinstance(exc, DjangoValidationError):
        exc = ValidationError(detail=getattr(exc, "message_dict", None) or exc.messages)
    elif isinstance(exc, DjangoPermissionDenied):
        exc = APIException(detail=str(exc) or "Доступ запрещён")
        exc.status_code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, Http404):
        exc = APIException(detail="Ресурс не найден")
        exc.status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, IntegrityError):
        logger.warning("integrity_error", error=str(exc)[:300])
        return Response(
            {
                "data": None,
                "meta": None,
                "errors": [
                    {
                        "code": "conflict",
                        "field": None,
                        "message": "Нарушена целостность данных: возможно, объект уже существует",
                    }
                ],
            },
            status=status.HTTP_409_CONFLICT,
        )

    response = drf_exception_handler(exc, context)

    if response is None:
        logger.error("unhandled_exception", error=str(exc), exc_info=exc)
        return Response(
            {
                "data": None,
                "meta": None,
                "errors": [
                    {"code": "server_error", "field": None, "message": "Внутренняя ошибка сервера"}
                ],
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    detail = response.data
    code = getattr(exc, "default_code", "error")

    if isinstance(detail, dict) and "detail" in detail and len(detail) == 1:
        errors = [{"code": str(code), "field": None, "message": str(detail["detail"])}]
    elif isinstance(detail, dict) and set(detail) == {"code", "message"}:
        errors = [{"code": str(detail["code"]), "field": None, "message": str(detail["message"])}]
    else:
        errors = _flatten(detail)

    response.data = {"data": None, "meta": None, "errors": errors}
    return response
