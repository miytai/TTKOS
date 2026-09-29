"""Метрики Prometheus без внешних зависимостей (TECHSPEC §17.8).

Минимальный in-process регистр: счётчики, гистограммы и gauge-подобные
значения, которые отдаёт ``/api/metrics/`` в текстовом формате Prometheus.
"""

import threading
import time
from collections import defaultdict, deque

_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 10.0)


class Registry:
    """Потокобезопасный реестр метрик."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], deque] = defaultdict(
            lambda: deque(maxlen=1000)
        )
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._help: dict[str, str] = {}

    @staticmethod
    def _key(name: str, labels: dict | None):
        return name, tuple(sorted((labels or {}).items()))

    def counter_inc(self, name: str, labels: dict | None = None, value: float = 1.0) -> None:
        with self._lock:
            self._counters[self._key(name, labels)] += value

    def histogram_observe(self, name: str, value: float, labels: dict | None = None) -> None:
        with self._lock:
            self._histograms[self._key(name, labels)].append(value)

    def gauge_set(self, name: str, value: float, labels: dict | None = None) -> None:
        with self._lock:
            self._gauges[self._key(name, labels)] = value

    def describe(self, name: str, help_text: str) -> None:
        self._help[name] = help_text

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._histograms.clear()
            self._gauges.clear()

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            histograms = {k: list(v) for k, v in self._histograms.items()}

        def label_str(labels) -> str:
            if not labels:
                return ""
            inner = ",".join(f'{k}="{v}"' for k, v in labels)
            return "{" + inner + "}"

        for (name, labels), value in counters.items():
            if name not in self._help:
                self._help[name] = f"Forumos {name}"
            lines.append(f"# HELP {name} {self._help[name]}")
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name}{label_str(labels)} {value}")

        for (name, labels), value in gauges.items():
            self._help.setdefault(name, f"Forumos {name}")
            lines.append(f"# HELP {name} {self._help[name]}")
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name}{label_str(labels)} {value}")

        for (name, labels), samples in histograms.items():
            self._help.setdefault(name, f"Forumos {name}")
            lines.append(f"# HELP {name} {self._help[name]}")
            lines.append(f"# TYPE {name} histogram")
            for bucket in _BUCKETS:
                count = sum(1 for s in samples if s <= bucket)
                bucket_labels = (*labels, ("le", str(bucket)))
                lines.append(f"{name}_bucket{label_str(bucket_labels)} {count}")
            lines.append(f"{name}_bucket{label_str((*labels, ('le', '+Inf')))} {len(samples)}")
            lines.append(f"{name}_sum{label_str(labels)} {sum(samples):.6f}")
            lines.append(f"{name}_count{label_str(labels)} {len(samples)}")

        return "\n".join(lines) + "\n"


registry = Registry()

registry.describe("http_requests_total", "Total HTTP requests")
registry.describe("http_request_duration_seconds", "HTTP request duration in seconds")
registry.describe("ws_connections", "Currently open websocket connections")
registry.describe("celery_queue_length", "Celery queue length")
registry.describe("kafka_consumer_group_lag", "Kafka consumer group lag")
registry.describe("api_errors_total", "API errors by code")


def observe_request(path: str, method: str, status: int, duration: float) -> None:
    """Записать метрики HTTP-запроса."""
    labels = {"path": path, "method": method, "status": str(status)}
    registry.counter_inc("http_requests_total", labels)
    registry.histogram_observe(
        "http_request_duration_seconds", duration, {"path": path, "method": method}
    )


def set_gauge(name: str, value: float, labels: dict | None = None) -> None:
    registry.gauge_set(name, value, labels)


def record_event(name: str, duration: float | None = None) -> None:
    """Универсальная запись события (Kafka-события, задачи Celery)."""
    registry.counter_inc("events_total", {"event": name})
    if duration is not None:
        registry.histogram_observe("event_duration_seconds", duration, {"event": name})


class Timer:
    """Контекстный менеджер для замера длительности."""

    def __init__(self, name: str, labels: dict | None = None) -> None:
        self.name = name
        self.labels = labels
        self.start = 0.0

    def __enter__(self) -> "Timer":
        self.start = time.perf_counter()
        return self

    def __exit__(self, *_exc) -> None:
        self.duration = time.perf_counter() - self.start
        self.value = self.duration
        registry.histogram_observe(self.name, self.duration, self.labels)
