"""Наполнение справочников и демо-данных (TECHSPEC §10.2)."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

UserModel = get_user_model()

REACTIONS = [
    {"code": "like", "emoji": "👍", "karma_value": 1, "order": 1},
    {"code": "fire", "emoji": "🔥", "karma_value": 2, "order": 2},
    {"code": "laugh", "emoji": "😂", "karma_value": 0, "order": 3},
    {"code": "sad", "emoji": "😢", "karma_value": 0, "order": 4},
    {"code": "wow", "emoji": "😮", "karma_value": 1, "order": 5},
]

FORUMS = [
    {"name": "Разработка", "slug": "dev", "icon": "💻", "accent": "#7dd3a0", "order": 1,
     "description": "Код, архитектура, ревью и помощь с багами."},
    {"name": "Дизайн", "slug": "design", "icon": "🎨", "accent": "#f4a261", "order": 2,
     "description": "Интерфейсы, типографика, accessibility."},
    {"name": "Продукт", "slug": "product", "icon": "🧭", "accent": "#89b4fa", "order": 3,
     "description": "Идеи, метрики, роадмапы и обратная связь."},
    {"name": "Сообщество", "slug": "community", "icon": "🌿", "accent": "#c9ada7", "order": 4,
     "description": "Правила, знакомства, оффлайн-встречи."},
    {"name": "Флудилка", "slug": "offtopic", "icon": "☕", "accent": "#a8a29e", "order": 90,
     "description": "Свободное общение без модерации тем."},
]

TAGS = ["devops", "guide", "backend", "frontend", "design", "career", "tools", "security"]

SEO_RECORDS = [
    {"path": "/", "title": "ForumOS — форум о разработке и технологиях",
     "description": "Спокойное место для обсуждения кода, дизайна и продуктовых решений.",
     "priority": 1.0, "robots": "index, follow"},
    {"path": "/f/dev", "title": "Разработка — ForumOS",
     "description": "Backend, frontend, DevOps и архитектура.", "priority": 0.8},
    {"path": "/search", "title": "Поиск — ForumOS",
     "description": "Полнотекстовый поиск по темам, постам и профилям.", "priority": 0.4,
     "robots": "noindex, follow"},
]


class Command(BaseCommand):
    """``python manage.py seed`` — наполнение справочников (TECHSPEC §10.2)."""

    help = "Наполняет справочники: реакции, разделы, теги, ачивки, SEO-записи"

    def add_arguments(self, parser) -> None:
        parser.add_argument("--demo", action="store_true",
                            help="Дополнительно создать демо-пользователя и темы")

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        self._seed_reactions()
        self._seed_forums()
        self._seed_tags()
        self._seed_achievements()
        self._seed_seo()
        self._ensure_site()
        if options.get("demo"):
            self._seed_demo()
        self.stdout.write(self.style.SUCCESS("Сиды применены"))

    def _seed_reactions(self) -> None:
        from apps.reactions.models import Reaction

        for item in REACTIONS:
            Reaction.objects.update_or_create(code=item["code"], defaults=item)
        self.stdout.write(f"Реакции: {Reaction.objects.count()}")

    def _seed_forums(self) -> None:
        from apps.forums.models import Forum

        for item in FORUMS:
            Forum.objects.update_or_create(slug=item["slug"], defaults=item)
        self.stdout.write(f"Разделы: {Forum.objects.count()}")

    def _seed_tags(self) -> None:
        from apps.threads.models import Tag

        for name in TAGS:
            Tag.objects.get_or_create(name=name)
        self.stdout.write(f"Теги: {Tag.objects.count()}")

    def _seed_achievements(self) -> None:
        from apps.accounts.services import seed_achievements

        self.stdout.write(f"Ачивки: {len(seed_achievements())}")

    def _seed_seo(self) -> None:
        from apps.seo.models import SEOMeta

        for item in SEO_RECORDS:
            SEOMeta.objects.update_or_create(path=item["path"], defaults=item)
        self.stdout.write(f"SEO-записи: {SEOMeta.objects.count()}")

    def _ensure_site(self) -> None:
        from django.conf import settings
        from django.contrib.sites.models import Site

        Site.objects.update_or_create(
            pk=settings.SITE_ID,
            defaults={"domain": "localhost:8080", "name": settings.APP_NAME},
        )

    def _seed_demo(self) -> None:
        from apps.accounts.models import Rank
        from apps.accounts.services import register_user
        from apps.forums.models import Forum
        from apps.threads.services import create_thread

        if not UserModel.objects.filter(username="demo").exists():
            demo, _ = register_user(email="demo@forumos.local", username="demo",
                                    password="DemoPassw0rd!")
            demo.is_email_verified = True
            demo.save(update_fields=["is_email_verified"])
            profile = demo.userprofile
            profile.rank = Rank.MEMBER
            profile.reputation = 50
            profile.bio = "Демонстрационный аккаунт для локального стенда."
            profile.save()
            self.stdout.write("Демо-пользователь: demo / DemoPassw0rd!")

        demo_user = UserModel.objects.filter(username="demo").first()
        if demo_user and not demo_user.threads.exists():
            create_thread(
                author=demo_user,
                forum=Forum.objects.get(slug="dev"),
                title="Добро пожаловать в ForumOS",
                body="Это демонстрационная тема. Она создана командой `make seed`.",
                tags=["guide"],
            )
            self.stdout.write("Демо-тема создана")
