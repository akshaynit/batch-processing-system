# syntax=docker/dockerfile:1
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first (better layer caching). README is referenced by
# project metadata, so it must be present for the install to succeed.
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install .

# Runtime-only files (migrations config, entrypoints, helper scripts).
COPY alembic.ini ./
COPY scripts ./scripts
COPY workers ./workers
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Drop privileges.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

ENTRYPOINT ["entrypoint.sh"]
CMD ["api"]
