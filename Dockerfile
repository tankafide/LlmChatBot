FROM ghcr.io/astral-sh/uv:0.8.13 AS uv
FROM python:3.13.7-slim-bookworm

COPY --from=uv /uv /uvx /bin/
WORKDIR /app

RUN groupadd --gid 10001 autoassist \
    && useradd --uid 10001 --gid autoassist --create-home autoassist \
    && mkdir -p /app/config \
    && chown -R autoassist:autoassist /app

COPY --chown=autoassist:autoassist backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-install-project

COPY --chown=autoassist:autoassist backend/src ./src
COPY --chown=autoassist:autoassist README.md ./README.md
COPY --chown=autoassist:autoassist config/dealerships.json ./config/dealerships.json
RUN uv sync --frozen

USER autoassist
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    AUTOASSIST_CONFIG_FILE=/app/config/dealerships.json \
    AUTOASSIST_DATABASE_URL=postgresql+psycopg://autoassist:autoassist-dev@database:5432/autoassist

EXPOSE 8000
CMD ["uvicorn", "autoassist.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--timeout-graceful-shutdown", "10"]
