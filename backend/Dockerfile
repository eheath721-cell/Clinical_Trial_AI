FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
RUN pip install ".[llm]"

COPY alembic.ini ./
COPY alembic ./alembic
COPY data ./data

RUN useradd --create-home --uid 10001 appuser && mkdir -p /app/var/documents && chown -R appuser /app/var
USER appuser

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
