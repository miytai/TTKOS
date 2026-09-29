"""Полная переиндексация Elasticsearch из CLI (TECHSPEC §5.3)."""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """``python manage.py reindex [threads|posts|users]``."""

    help = "Синхронно переиндексирует сущности в Elasticsearch"

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "entity",
            nargs="?",
            default="",
            choices=["", "threads", "posts", "users"],
            help="Ограничить переиндексацию одной сущностью",
        )

    def handle(self, *args, **options) -> None:
        from apps.search import service
        from apps.search.tasks import reindex_all

        entity = options["entity"] or None
        self.stdout.write(f"Создание индексов: {', '.join(service.MAPPINGS)}")
        service.ensure_indices()
        stats = reindex_all.apply(args=[entity]).get()
        for name, count in stats.items():
            self.stdout.write(f"  {name}: {count} документов")
        self.stdout.write(self.style.SUCCESS("Переиндексация завершена"))
