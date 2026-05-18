.PHONY: up down logs ps migrate dev worker install lint format test

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

migrate:
	uv run alembic upgrade head

dev:
	uv run uvicorn film.main:app --reload --port 8000

worker:
	uv run python -m film.temporal.worker

install:
	uv sync --all-extras

lint:
	uv run ruff check film/ tests/

format:
	uv run ruff format film/ tests/
	uv run ruff check --fix film/ tests/

test:
	uv run pytest -v

test-integration:
	uv run pytest -v -m integration
