# Production image for Cloud Run Jobs.
# Build:  docker build -t lyra-daily .
# Run:    docker run --rm --env-file .env lyra-daily
#
# The Playwright-bundled Chromium works inside this image because
# python:3.13-slim provides a compatible glibc (unlike NixOS).

FROM python:3.13-slim

# Install uv (fast package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml uv.lock README.md ./
RUN mkdir -p lyra && touch lyra/__init__.py
RUN uv sync --frozen --no-dev

# Install Chromium with all system dependencies (~300 MB)
RUN uv run playwright install --with-deps chromium

# Copy application code
COPY lyra/ ./lyra/

# Production defaults (overridable via Cloud Run env vars)
ENV HEADLESS="true"
# Unset the NixOS workaround — Playwright's own Chromium works here
ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=""

CMD ["uv", "run", "python", "-m", "lyra", "daily"]
