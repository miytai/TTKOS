# ForumOS — Makefile
# Основные команды: make setup | make up | make dev | make test | make down

SHELL := /bin/bash
.DEFAULT_GOAL := help
COMPOSE := docker compose
DEV_COMPOSE := $(COMPOSE) -f docker-compose.yml

.PHONY: help
help: ## Показать список команд
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Подготовка ─────────────────────────────────────────────────────
.PHONY: setup
setup: ## Первичная настройка: .env, секреты, каталоги
	@test -f .env || cp .env.example .env
	@$(MAKE) secrets
	@mkdir -p backend/media backend/staticfiles logs

.PHONY: secrets
secrets: ## Сгенерировать случайные секреты в .env
	@python3 scripts/gen_secrets.py .env

.PHONY: sysctl
sysctl: ## Поднять лимит mmap для Elasticsearch (нужен sudo)
	sudo sysctl -w vm.max_map_count=262144 && echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-forumos.conf

# ── Запуск ─────────────────────────────────────────────────────────
.PHONY: up
up: ## Поднять весь стек (detached)
	$(DEV_COMPOSE) up -d --build
	@$(MAKE) ps

.PHONY: down
down: ## Остановить стек
	$(DEV_COMPOSE) down

.PHONY: destroy
destroy: ## Остановить стек и удалить volumes (данные!)
	$(DEV_COMPOSE) down -v

.PHONY: restart
restart: ## Перезапустить стек
	$(DEV_COMPOSE) restart

.PHONY: ps
ps: ## Статус контейнеров
	$(DEV_COMPOSE) ps

.PHONY: logs
logs: ## Логи сервиса (make logs SERVICE=backend)
	$(DEV_COMPOSE) logs -f --tail=200 $(SERVICE)

# ── Сервисы ────────────────────────────────────────────────────────
.PHONY: infra
infra: ## Поднять только инфраструктуру
	$(DEV_COMPOSE) up -d postgres redis kafka elasticsearch minio kafka-init minio-init

.PHONY: apps
apps: ## Поднять только приложения
	$(DEV_COMPOSE) up -d --build migrate backend channels celery-worker celery-beat frontend nginx

.PHONY: obs
obs: ## Поднять наблюдаемость (Prometheus, Grafana, Loki)
	$(DEV_COMPOSE) --profile observability up -d prometheus loki promtail grafana

.PHONY: backend-only
backend-only: ## Поднять backend + channels + celery без инфраструктуры
	$(DEV_COMPOSE) up -d --build migrate backend channels celery-worker celery-beat

# ── Django ─────────────────────────────────────────────────────────
.PHONY: migrate
migrate: ## Применить миграции
	$(DEV_COMPOSE) run --rm migrate python manage.py migrate --noinput

.PHONY: makemigrations
makemigrations: ## Создать миграции (make makemigrations APP=threads)
	$(DEV_COMPOSE) run --rm backend python manage.py makemigrations $(APP)

.PHONY: shell
shell: ## Django shell
	$(DEV_COMPOSE) run --rm backend python manage.py shell

.PHONY: superuser
superuser: ## Создать суперпользователя
	$(DEV_COMPOSE) run --rm backend python manage.py createsuperuser

.PHONY: seed
seed: ## Загрузить демо-данные
	$(DEV_COMPOSE) run --rm backend python manage.py seed --demo

.PHONY: reindex
reindex: ## Переиндексировать поиск (ENTITY=threads|posts|users)
	$(DEV_COMPOSE) run --rm backend python manage.py reindex $(ENTITY)

# ── Frontend ───────────────────────────────────────────────────────
.PHONY: frontend-install
frontend-install: ## Установить зависимости фронтенда
	$(DEV_COMPOSE) run --rm --no-deps frontend npm ci

.PHONY: frontend-build
frontend-build: ## Собрать фронтенд
	$(DEV_COMPOSE) run --rm --no-deps frontend npm run build

# ── Качество ───────────────────────────────────────────────────────
.PHONY: test
test: ## Тесты backend
	$(DEV_COMPOSE) run --rm backend pytest $(ARGS)

.PHONY: test-cov
test-cov: ## Тесты backend с покрытием
	$(DEV_COMPOSE) run --rm backend pytest --cov --cov-report=term-missing --cov-report=xml

.PHONY: test-frontend
test-frontend: ## Тесты фронтенда
	$(DEV_COMPOSE) run --rm --no-deps frontend npm run test

.PHONY: lint
lint: ## Линтеры backend + frontend
	$(DEV_COMPOSE) run --rm backend ruff check . && $(DEV_COMPOSE) run --rm backend ruff format --check .
	$(DEV_COMPOSE) run --rm --no-deps frontend npm run lint

.PHONY: fmt
fmt: ## Форматирование
	$(DEV_COMPOSE) run --rm backend ruff format . && $(DEV_COMPOSE) run --rm backend ruff check --fix .
	$(DEV_COMPOSE) run --rm --no-deps frontend npm run format

.PHONY: typecheck
typecheck: ## Проверка типов фронтенда
	$(DEV_COMPOSE) run --rm --no-deps frontend npm run typecheck

.PHONY: health
health: ## Проверить здоровье сервисов
	@curl -fsS http://localhost:8080/api/health/ | python3 -m json.tool

.PHONY: e2e
e2e: ## E2E-тесты Playwright
	$(COMPOSE) --profile e2e run --rm e2e

# ── Утилиты ────────────────────────────────────────────────────────
.PHONY: shell-py
shell-py: ## Оболочка backend без пересборки
	$(DEV_COMPOSE) exec backend bash

.PHONY: clean
clean: ## Удалить кэши
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf backend/.pytest_cache backend/.ruff_cache backend/htmlcov
