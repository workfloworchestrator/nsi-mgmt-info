# syntax=docker/dockerfile:1@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32
#
# Build stage
FROM ghcr.io/astral-sh/uv:python3.13-alpine@sha256:3ad497bedc14ffd0831dcd757d3c09ac8dfdb1d89d3e1ec47bbcb76f64a97c21 AS build
ARG VERSION
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_NSI_MGMT_INFO=${VERSION}
WORKDIR /app
COPY pyproject.toml LICENSE.txt README.md ./
COPY amiss amiss
COPY static static
RUN uv build --no-cache --wheel --out-dir dist

# Final stage
FROM ghcr.io/astral-sh/uv:python3.13-alpine@sha256:3ad497bedc14ffd0831dcd757d3c09ac8dfdb1d89d3e1ec47bbcb76f64a97c21
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
