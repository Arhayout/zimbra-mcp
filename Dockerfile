# syntax=docker/dockerfile:1
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.5.14 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim
RUN useradd --system --create-home --uid 10001 zimbra
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" ZIMBRA_STATE_DIR=/home/zimbra/state PYTHONUNBUFFERED=1
USER zimbra
WORKDIR /home/zimbra
# stdio transport: run with `docker run -i --rm --env-file ... zimbra-mcp`.
# Credentials come from the environment only; nothing is baked into the image.
ENTRYPOINT ["zimbra-mcp"]
