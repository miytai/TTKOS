"""Structured logging (TECHSPEC §5.8).

Используется structlog: JSON-вывод, request_id в контексте каждой записи.
"""

import logging
import sys

import structlog

_configured = False


def configure_logging() -> None:
    """Настроить structlog один раз на процесс."""
    global _configured
    if _configured:
        return

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logging.getLogger("forumos").handlers = [logging.StreamHandler(sys.stdout)]
    _configured = True


def get_logger(name: str = "forumos") -> structlog.stdlib.BoundLogger:
    """Вернуть логгер с привязанным именем модуля."""
    configure_logging()
    return structlog.get_logger(name)


# ── Горячие пути (TECHSPEC §1.5: никаких print/console.log) ────────
def audit_log(event: str, **kwargs) -> None:
    """Структурированное событие для аудита (TECHSPEC §15.11)."""
    get_logger("forumos.audit").info(event, **kwargs)


def security_log(event: str, **kwargs) -> None:
    """Событие безопасности: входы, отказы, лимиты."""
    get_logger("forumos.security").warning(event, **kwargs)
