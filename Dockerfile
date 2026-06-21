FROM python:3.12-slim

# Copy uv binary from the official image
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

WORKDIR /app

# Copy dependency manifest first — maximises Docker layer cache reuse
COPY pyproject.toml uv.lock ./

# Install production dependencies only; --no-dev excludes ruff/pytest from the image
RUN uv sync --frozen --no-cache --no-dev

# Copy application source after deps for better layer caching
COPY . .

# Run with the venv's uvicorn directly
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
