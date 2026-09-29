#!/usr/bin/env python3
"""Генерация случайных секретов в .env (TECHSPEC §15.9).

Использование: python3 scripts/gen_secrets.py [путь к .env]
Ключи, которых нет в файле, добавляются в конец. Существующие комментарии
и порядок переменных сохраняются.
"""

from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path

SECRET_KEYS = (
    "DJANGO_SECRET_KEY",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "ELASTIC_PASSWORD",
    "MINIO_ROOT_PASSWORD",
    "JWT_SIGNING_KEY",
    "GRAFANA_ADMIN_PASSWORD",
    "DJANGO_SUPERUSER_PASSWORD",
)


def new_secret() -> str:
    """URL-safe строка без символов, которые ломают .env и URL."""
    return secrets.token_urlsafe(48)


def patch(text: str) -> str:
    """Заменить значения секретов, сохранив комментарии и порядок строк."""
    for key in SECRET_KEYS:
        pattern = re.compile(rf"(?m)^{key}=.*$")
        text, count = pattern.subn(f"{key}={new_secret()}", text)
        if count == 0:
            text = f"{text.rstrip()}\n{key}={new_secret()}\n"
    return text


def main() -> int:
    env_path = Path(sys.argv[1] if len(sys.argv) > 1 else ".env")
    if not env_path.exists():
        example = env_path.with_name(f"{env_path.name}.example")
        if not example.exists():
            print(f"ERR: neither {env_path} nor {example} found", file=sys.stderr)
            return 1
        env_path.write_text(example.read_text(), encoding="utf-8")
        print(f"Created {env_path} from {example}")

    env_path.write_text(patch(env_path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Secrets generated in {env_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
