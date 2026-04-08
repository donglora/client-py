set shell := ["bash", "-c"]

default: check

[private]
_ensure_tools:
    @mise trust --yes . 2>/dev/null; mise install --quiet

# Run all checks (fmt, lint, test)
check: fmt-check lint test

# Format code
fmt: _ensure_tools
    @uv run ruff format .

# Check formatting without changing files
fmt-check: _ensure_tools
    @uv run ruff format --check .

# Lint
lint: _ensure_tools
    @uv run ruff check .

# Run tests
test: _ensure_tools
    @uv run pytest -v
