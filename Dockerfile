# syntax=docker/dockerfile:1@sha256:572cebbc2b15e6f84c077742952674889cb63cd5e9b80abdffcbe587b6f19183
#
# Build stage
FROM ghcr.io/astral-sh/uv:python3.13-alpine@sha256:6e3e7a0061d007bf3d7f1b24c258b62f384ef14fbe2df673493d2b53e88b526b AS build
ARG VERSION
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_NSI_MGMT_INFO=${VERSION}
WORKDIR /app
COPY pyproject.toml LICENSE.txt README.md ./
COPY amiss amiss
COPY static static
RUN uv build --no-cache --wheel --out-dir dist

# Final stage
FROM ghcr.io/astral-sh/uv:python3.13-alpine@sha256:6e3e7a0061d007bf3d7f1b24c258b62f384ef14fbe2df673493d2b53e88b526b
# Drops emSign ECC Root CA - G3 (ca-certificates 20261020); remove once the base image has it.
RUN apk upgrade --no-cache ca-certificates ca-certificates-bundle
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
