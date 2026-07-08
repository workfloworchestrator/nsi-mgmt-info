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
uv run --group dev pytest tests/test_vlan.py -v

# Run a specific test
uv run --group dev pytest tests/ -k "test_free_vlan_ranges"

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

**App initialization** (`amiss/__init__.py`): Creates the FastAPI app, mounts static files at `/static`, registers all routers, and defines a catch-all `/{path:path}` route that serves FastUI's prebuilt React SPA HTML. Seeding and the APScheduler poller run **only when `NSI_AMISS_DATABASE_ENABLED`** is set; in the default live mode neither runs.

**Live data flow** (`amiss/data.py`, `amiss/sources/`): the default. Routes call `amiss/data.py` (`get_circuits`/`get_stps`/`get_sdps`), which queries the **WFO orchestrator GraphQL** per request (forwarding the caller's OIDC token) and reconciles STP/SDP subscriptions against the DDS topology. `NSI_AMISS_DATABASE_ENABLED` is intended to switch these accessors to reading a DB cache filled by the poller; that read path is not implemented yet (needs a WFO service identity), so it currently serves live regardless.

**Frontend** (`amiss/frontend/`): FastAPI routers return FastUI JSON component trees, not HTML. The React SPA (served by `prebuilt_html()`) fetches these JSON responses and renders them client-side. Routes are **read-only** and there is **one view per table** (no active/inactive/all tabs): `/circuits` (list + live-refetched detail by subscription id), `/stp`, `/sdp` (each a WFO-vs-DDS reconciliation with server-side `?sort=`), `/spectrum` (still DB-backed, deferred), healthcheck. A source failure renders a warning banner rather than a misleading table.

**State machine** (`amiss/fsm.py`): `ConnectionStateMachine` (python-statemachine) with 16 NSI-connection-lifecycle states. Retained only for its state `.value` constants; the live circuits view shows the WFO `vc.state` string and no longer filters by these values.

**Background jobs** (`amiss/job.py`, `amiss/agg.py`): APScheduler poller, **only started when `NSI_AMISS_DATABASE_ENABLED`**. It polls the DDS and aggregator proxies into the DB (`Circuit`/`Segment`/`STP`/`SDP`) — the legacy cache path, being superseded by the WFO source; the WFO poller is a follow-up.

**NSI integration** (`amiss/nsi.py`, `amiss/dds.py`, `amiss/sources/`): `nsi.py` is the JSON `GET`/POST helper set (`nsi_util_get_json`, plus the WFO client in `sources/wfo.py`). `sources/wfo.py` queries the WFO GraphQL (`<NSI_AMISS_WFO_URL>/api/graphql`, Bearer token) and maps MDP2P/STP/SDP subscriptions to render DTOs; `sources/dds_topology.py` reads the DDS proxy topology (reusing `amiss/dds.py`) as reconciliation DTOs; `sources/reconcile.py` diffs the two (IN_BOTH / DDS_ONLY / MISSING_IN_DDS).

**Database** (`amiss/db.py`, `amiss/model.py`): SQLModel ORM, now an **opt-in cache** (`NSI_AMISS_DATABASE_ENABLED`, default off). Defaults to a shared **in-memory** SQLite database (`sqlite:///file::memory:?cache=shared&uri=true`, ephemeral; `db.py` uses a `StaticPool` + `check_same_thread=False`). File-based SQLite or PostgreSQL via `DATABASE_URI`. Table models: `STP`, `SDP`, `Circuit` (formerly `Reservation`; references source/dest `STP`, links many-to-many to `SDP`), `CircuitSDPLink` (the Circuit↔SDP association table), `Segment` (child of a `Circuit` via the `circuit_id` FK), `Log` (audit trail).

**Static files packaging**: `pyproject.toml` uses `[tool.setuptools.data-files]` to install static assets to `share/amiss/static/` in the wheel. The Dockerfile sets `STATIC_DIRECTORY=/usr/local/share/amiss/static` to point to the installed location.

## ROOT_PATH design decision

When deployed behind a reverse-proxy portal, the app is served at path prefix `/amiss`. The portal's nginx ingress strips this prefix before forwarding requests.

**Do NOT set `FastAPI(root_path=...)`**. Starlette's `get_route_path()` assumes `scope["path"]` contains `root_path` as a prefix. When the proxy already stripped the prefix, this causes StaticFiles to double-count the mount path (looking up `static/static/file.png`), resulting in 404s.

Instead, `settings.ROOT_PATH` is used only for URL prefixing in templates and forms:
- `prebuilt_html(api_root_url=..., api_path_strip=...)` in the catch-all route
- Image `src` attributes via `amiss/frontend/util.py`
- Table sort and detail URLs in `amiss/frontend/circuits.py`

## Testing

The test setup in `conftest.py` has important ordering constraints:
- `DATABASE_URI` is set to `sqlite://` (in-memory) **before any amiss imports** because `Settings` validates `FilePath` fields at import time
- Dummy PEM files (`amiss-certificate.pem`, `amiss-private-key.pem`) are created before imports for the same reason
- `DatabaseLogHandler` is removed from all loggers to prevent DB writes during tests
- Each test gets its own DB session with automatic rollback via a transaction wrapper

## Code style

- Line length: 120
- Formatting and linting: `ruff format` + `ruff check` (ruff is the single tool — black/isort/flake8 removed)
- Python target: 3.13
- mypy with `pydantic.mypy` plugin, `disallow_untyped_defs = true`
- ruff rules: ANN, ARG, B, C, D, E, F, I, N, PGH, PTH, Q, RET, RUF, S, T, W; tests exempt from ANN/S101/docstring rules via `per-file-ignores`
