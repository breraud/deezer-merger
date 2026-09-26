# Image construite par la CI et poussee sur ghcr.io : le VPS ne build rien.
# uv 0.12 n'est publie qu'en trixie. Les deux etapes doivent nommer la meme
# version de Debian : le venv construit ici est copie tel quel plus bas.
FROM ghcr.io/astral-sh/uv:0.12-python3.12-trixie-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev


FROM python:3.12-slim-trixie AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser main.py deezer_client.py ./
COPY --chown=appuser:appuser static ./static

USER appuser

EXPOSE 3457

# 0.0.0.0 est obligatoire : le conteneur est joint par Traefik via le reseau
# docker, pas par la loopback. L'exposition publique est controlee par Traefik.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3457"]
