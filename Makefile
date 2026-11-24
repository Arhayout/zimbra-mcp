.PHONY: install check run-http test

install:
	uv sync

check:
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy
	uv run pytest

run-http:
	uv run zimbra-mcp --transport streamable-http --host 127.0.0.1 --port 8000

test:
	uv run pytest
