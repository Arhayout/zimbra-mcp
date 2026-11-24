FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev
COPY src ./src

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "zimbra-mcp", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
