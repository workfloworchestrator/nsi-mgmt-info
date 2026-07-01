# syntax=docker/dockerfile:1@sha256:87999aa3d42bdc6bea60565083ee17e86d1f3339802f543c0d03998580f9cb89
#
# Build stage
FROM ghcr.io/astral-sh/uv:python3.13-alpine@sha256:4ecced75748f17027a8e81d2918252972c64e91deebc80dad801b601ed6ca0f0 AS build
WORKDIR /app
COPY pyproject.toml LICENSE.txt README.md ./
COPY amiss amiss
COPY static static
RUN uv build --no-cache --wheel --out-dir dist

# Final stage
FROM ghcr.io/astral-sh/uv:python3.13-alpine@sha256:4ecced75748f17027a8e81d2918252972c64e91deebc80dad801b601ed6ca0f0
COPY --from=build /app/dist/*.whl /tmp/
RUN uv pip install --system --no-cache /tmp/*.whl && rm /tmp/*.whl
RUN addgroup -g 1000 amiss && adduser -D -u 1000 -G amiss amiss
USER amiss
WORKDIR /home/amiss
EXPOSE 8080/tcp
ENV STATIC_DIRECTORY=/usr/local/share/amiss/static
# Serve on all interfaces and the exposed port (app defaults are 127.0.0.1:8000)
ENV NSI_AMISS_HOST=0.0.0.0 NSI_AMISS_PORT=8080
CMD ["nsi-mgmt-info"]
