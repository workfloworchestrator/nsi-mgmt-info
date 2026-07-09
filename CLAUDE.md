# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

The **NSI Management Information Service** — a FastAPI + FastUI web service that surfaces and visualizes the information ANA management needs for strategic and engineering decision-making, aggregating data from the NSI-Orchestrator and other ANA-NSI components into overviews and statistics. **`README.md` is the ground truth** for the project's purpose and configuration.

**Naming.** The product and UI brand is **AMISS** (the default `SITE_TITLE` in `amiss/settings.py`). The importable Python package is `amiss` (config file `amiss.env`, `NSI_AMISS_*` settings), while the distribution, console script, Helm chart, container image, GitHub repository, and requester-NSA URN all use **`nsi-mgmt-info`**. Config variable names follow `amiss/settings.py`. The codebase originated from the older **NSI-AuRA** (uRA — ultimate Requester Agent) application, since superseded by nsi-dds-proxy, nsi-aggregator-proxy, and nsi-orchestrator.

## Commands

```bash
# Run all tests (matches CI)
uv run --group dev pytest tests/ -v

# Run a single test file
uv run --group dev pytest tests/sources/test_aggregator.py -v

# Run a specific test
uv run --group dev pytest tests/ -k "spectrum"

# Type checking
uv run --group dev mypy amiss/

# Linting and format check (matches CI)
uv run --group dev ruff check .
uv run --group dev ruff format --check .

# Build wheel
uv build --wheel

# Run locally (requires amiss.env with certificate paths and NSI URLs)
nsi-mgmt-info
```

## Architecture

**App initialization** (`amiss/__init__.py`): Creates the FastAPI app, mounts static files at `/static`, adds the `log_request_time` middleware, registers all routers, injects a small `_BRAND_STYLE` block (teal ANA navbar/background, to match `ana-automation-ui`) into the prebuilt SPA shell, and defines a catch-all `/{path:path}` route that serves FastUI's prebuilt React SPA HTML. There is no database or scheduler — everything is served live per request.

**Live data flow** (`amiss/data.py`, `amiss/sources/`): Routes call `amiss/data.py` (`get_circuits`/`get_stps`/`get_sdps`/`get_spectrum`/`get_circuit_path`), which queries the **WFO orchestrator GraphQL** per request (forwarding the caller's OIDC token) and reconciles STP/SDP subscriptions against the DDS topology. Accessors that need more than one upstream fetch them **concurrently** (`ThreadPoolExecutor`), so a page's wall-clock ≈ the slowest single fetch. No cache — every page is live.

**Performance.** Each page fetches live; the dominant cost is a **fixed ~400–500 ms per WFO GraphQL request** (independent of payload — responses are a few KB, JSON parse ≈ 0), attributable to per-request OIDC token validation + GraphQL/DB setup at the orchestrator, so one WFO round-trip is the per-page floor. The `log_request_time` middleware in `__init__.py` logs `elapsed_ms` per request at **DEBUG**. See README **Performance** for improvement directions (biggest: cache token validation orchestrator-side; AMISS-side: batch the dashboard's three WFO queries into one aliased request).

**Frontend** (`amiss/frontend/`): FastAPI routers return FastUI JSON component trees, not HTML. The React SPA (served by `prebuilt_html()`) fetches these JSON responses and renders them client-side. Routes are **read-only**: `/` (`home.py`) is a summary **dashboard** that fetches each upstream once, concurrently, and composes its cards from the shared results via the same pure builders the pages use (no duplicate WFO queries); `/circuits` (`circuits.py`) is a list with four **state tabs** — Activated / Failed / Terminated / All (bucketed by `circuit_state_bucket(vc.state)`) — plus a live-refetched detail by subscription id that also shows the aggregator **path** segments (`get_circuit_path`); `/stp`, `/sdp` are single WFO-vs-DDS reconciliation views with server-side `?sort=`; `/spectrum` (`spectrum.py`) lists the SDPs with the circuits crossing each (WFO SDP subscriptions + aggregator-proxy paths) with a per-SDP drill-in; `/healthcheck` rounds it out. A source failure renders a warning banner rather than a misleading table.

**NSI integration** (`amiss/nsi.py`, `amiss/dds.py`, `amiss/sources/`): `nsi.py` is the JSON `GET`/POST helper set (`nsi_util_get_json`, plus the WFO client in `sources/wfo.py`). `sources/wfo.py` queries the WFO GraphQL (`<NSI_AMISS_WFO_URL>/api/graphql`, Bearer token) and maps MDP2P/STP/SDP subscriptions to render DTOs; `sources/dds_topology.py` reads the DDS proxy topology (reusing `amiss/dds.py`) as reconciliation DTOs; `sources/reconcile.py` diffs the two (IN_BOTH / DDS_ONLY / MISSING_IN_DDS); `sources/aggregator.py` fetches circuit paths from the aggregator proxy (`GET /reservations?detail=full` via `nsi_util_get_json`, same mTLS identity as the DDS proxy) and `build_spectrum()` groups circuits under the SDP they cross (subset of touched STPs).

**Static files packaging**: `pyproject.toml` uses `[tool.setuptools.data-files]` to install static assets to `share/amiss/static/` in the wheel. The Dockerfile sets `STATIC_DIRECTORY=/usr/local/share/amiss/static` to point to the installed location.

## ROOT_PATH design decision

When deployed behind a reverse-proxy portal, the app is served at path prefix `/amiss`. The portal's nginx ingress strips this prefix before forwarding requests.

**Do NOT set `FastAPI(root_path=...)`**. Starlette's `get_route_path()` assumes `scope["path"]` contains `root_path` as a prefix. When the proxy already stripped the prefix, this causes StaticFiles to double-count the mount path (looking up `static/static/file.png`), resulting in 404s.

Instead, `settings.ROOT_PATH` is applied explicitly to every URL the frontend emits, via the
`root_url(path)` helper in `amiss/frontend/util.py`. FastUI's `api_path_strip` expects the browser
path to **keep** the prefix (it strips it only for the API fetch), so a bare `GoToEvent(url="/x")`
would navigate the browser to `/x` and drop the `/amiss`. Everything internal must be prefixed:
- `prebuilt_html(api_root_url=..., api_path_strip=...)` in the catch-all route
- every `GoToEvent(url=...)` (navbar title + links, dashboard cards, tabs, table row/detail links,
  Back buttons) and each navbar/tab `active` matcher
- `sort_form` `submit_url`s and image `src` attributes

`root_url` is a no-op when `ROOT_PATH` is empty (local/dev). External links (e.g. the GitHub footer)
are left absolute.

## Testing

The test setup in `conftest.py` creates dummy PEM files (`amiss-certificate.pem`, `amiss-private-key.pem`) **before any amiss imports**, because `Settings` validates its `FilePath` fields at import time. Upstreams are mocked per test (`unittest.mock.patch` for units; the `responses` library for the integration stack in `tests/integration/`).

## Code style

- Line length: 120
- Formatting and linting: `ruff format` + `ruff check` (ruff is the single tool — black/isort/flake8 removed)
- Python target: 3.13
- mypy with `pydantic.mypy` plugin, `disallow_untyped_defs = true`
- ruff rules: ANN, ARG, B, C, D, E, F, I, N, PGH, PTH, Q, RET, RUF, S, T, W; tests exempt from ANN/S101/docstring rules via `per-file-ignores`
