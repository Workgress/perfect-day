.PHONY: up down logs ps test lint psql redis-cli migrate downgrade revision

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

ps:
	docker compose ps

test:
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check . && uv run mypy app

psql:
	docker compose exec postgres sh -c 'psql -U $$POSTGRES_USER -d $$POSTGRES_DB'

redis-cli:
	docker compose exec redis redis-cli

migrate:
	docker compose run --rm migrate alembic upgrade head

downgrade:
	docker compose run --rm migrate alembic downgrade -1

revision:
	uv run alembic revision --autogenerate -m "$(m)"
