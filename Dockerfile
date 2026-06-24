# Production image — build and run locally or in CI.
# Build:  docker build -t lyra-daily .
# Run:    docker run --rm --env-file .env lyra-daily
#
# The Playwright-bundled Chromium works inside this image because
# python:3.13-slim provides a compatible glibc (unlike NixOS).

FROM python:3.13-slim

# Install uv (fast package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy the full application (including pyproject.toml and lyra/)
COPY pyproject.toml uv.lock README.md ./
COPY lyra/ ./lyra/

# Install Python dependencies (package is present, no workarounds needed)
RUN uv sync --frozen --no-dev

# Install Chromium OS dependencies as root, then the browser binary as
# the non-root user so Playwright can find it at runtime.
RUN uv run playwright install-deps chromium
RUN useradd -m lyra && chown -R lyra:lyra /app
USER lyra
RUN uv run playwright install chromium

# Production defaults (overridable via env vars)
ENV HEADLESS="true"
# Unset the NixOS workaround — Playwright's own Chromium works here
ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=""

CMD ["uv", "run", "python", "-m", "lyra", "daily"]
