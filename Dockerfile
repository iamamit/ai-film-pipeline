FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml .
RUN uv pip install --system .

COPY film/ ./film/
COPY alembic/ ./alembic/
COPY alembic.ini .

EXPOSE 8000
CMD ["uvicorn", "film.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
