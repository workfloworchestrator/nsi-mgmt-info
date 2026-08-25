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

**Live data flow** (`amiss/data.py`, `amiss/sources/`): Routes call `amiss/data.py` (`get_circuits`/`get_topologies`/`get_switching_services`/`get_stps`/`get_sdps`/`get_spectrum`/`get_circuit_path`), which queries the **WFO orchestrator GraphQL** per request (forwarding the caller's OIDC token) and reconciles Topology/SwitchingService/STP/SDP subscriptions against the DDS topology. Accessors that need more than one upstream fetch them **concurrently** (`ThreadPoolExecutor`), so a page's wall-clock ≈ the slowest single fetch. No cache — every page is live. Each accessor returns a `rows`/`error` model, never raising: a fetch failure arrives as `None` from the source, except a credentials refusal, which `query_wfo` raises as `WfoUnauthorizedError` so the pages can word it as `NOT_AUTHORIZED` instead of an outage. Only the WFO leg does this — the DDS/aggregator legs use AMISS's own identity, where a 401/403 is a deployment fault, not something the user can act on.

**Performance.** Each page fetches live; the dominant cost is a **fixed ~400–500 ms per WFO GraphQL request** (independent of payload — responses are a few KB, JSON parse ≈ 0), attributable to per-request OIDC token validation + GraphQL/DB setup at the orchestrator, so one WFO round-trip is the per-page floor. The `log_request_time` middleware in `__init__.py` logs `elapsed_ms` per request at **DEBUG**. See README **Performance** for improvement directions (biggest: cache token validation orchestrator-side; AMISS-side: batch the dashboard's six WFO queries into one aliased request).

**Frontend** (`amiss/frontend/`): FastAPI routers return FastUI JSON component trees, not HTML. The React SPA (served by `prebuilt_html()`) fetches these JSON responses and renders them client-side. Routes are **read-only**: `/` (`home.py`) is a summary **dashboard** that fetches each upstream once, concurrently, and composes its six cards from the shared results via the same pure builders the pages use (no duplicate WFO queries), and ends with a **validation panel** listing failed `validate_*` / system-task processes (`fetch_validation_failures`, deduplicated per check+subscription so a nightly re-run stays one row); `/topology` and `/switching-service` (`inventory.py`) are WFO-vs-DDS reconciliation lists built from **one** router factory, since both products carry only an id and a name; `/circuits` (`circuits.py`) is a list with four **state tabs** — Activated / Failed / Terminated / All (bucketed by `circuit_state_bucket(vc.state)`) — plus a live-refetched detail by subscription id that also shows the aggregator **path** segments (`get_circuit_path`); `/stp` and `/sdp` are WFO-vs-DDS reconciliation views with server-side `?sort=` and status tabs (`reconcile_tabs`), each with a detail page keyed on subscription id — the STP one lists the circuits terminating on that port, the SDP one the circuits crossing it; `/spectrum` (`spectrum.py`) ranks the SDPs by reserved capacity and utilisation, linking each to its `/sdp` page rather than a drill-in of its own (the "Unattributed circuits" bucket has no SDP subscription to link to, so it is rendered inline); `/healthcheck` rounds it out. Every list table leads with the 8-char subscription id linking to that row's detail page (`_id_column`); rows without a subscription render it as an inert `—`. A source failure renders a warning banner rather than a misleading table,
and every page (the dashboard included) distinguishes *refused credentials* from *unreachable* — the two
look identical on screen but the first is fixed by re-authenticating or a group membership.

**NSI integration** (`amiss/nsi.py`, `amiss/dds.py`, `amiss/sources/`): `nsi.py` is the JSON `GET`/POST helper set (`nsi_util_get_json`, plus the WFO client in `sources/wfo.py`). `sources/wfo.py` queries the WFO GraphQL (`<NSI_AMISS_WFO_URL>/api/graphql`, Bearer token) and maps MDP2P/STP/SDP subscriptions to render DTOs; `sources/dds_topology.py` reads the DDS proxy topology (reusing `amiss/dds.py`, whose endpoint helpers all delegate to `get_dds_proxy_list`) as reconciliation DTOs; `sources/reconcile.py` diffs the two (IN_BOTH / DDS_ONLY / MISSING_IN_DDS), with `reconcile_named` serving both flat id-plus-name products and `normalize_id` stripping the URN prefix that the DDS side drops but the WFO keeps; `sources/aggregator.py` fetches circuit paths from the aggregator proxy (`GET /reservations?detail=full` via `nsi_util_get_json`, same mTLS identity as the DDS proxy) and `build_spectrum()` groups circuits under the SDP they cross (subset of touched STPs).

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

## Validation panel and inventory pages

**Three statuses, one filter.** `VALIDATION_FAILURES_QUERY` filters `lastStatus` on
`failed|inconsistent_data|api_unavailable`, because orchestrator-core treats the latter two as
distinct values that are *subtypes of* failed. Which one a failure gets is counter-intuitive: an
`AssertionError` in an `is_task` workflow (every `validate_*` in nsi-orchestrator) lands in
`inconsistent_data`, `InconsistentDataError` lands in plain `failed` (core compares the class name
against a literal `"InconsistentData"`, which no class matches), and an unreachable proxy also lands
in `failed`. Filtering on `"failed"` alone would therefore miss most of them. The filter language ORs
values split on `|`; `target` is the registered filter field, `workflowTarget` is response-side only.
The connection type is `ProcessTypeConnection`, not `ProcessConnection`.

Rows are deduplicated per `(workflow, subscription)` before rendering. The nightly fan-out re-runs
every validator, so an unrepaired problem would otherwise add a row per night and bury everything
else; `occurrences` carries the count. A system task has no subscription, so the key tolerates a null.

**No id links** on the validation table (which detail page a failure belongs to depends on its
product, and a system task has no subscription) or on the inventory tables (Topology and
SwitchingService have no detail page — the table already shows every field they carry).

**A `DDS only` row is normal**, not an alarm: the DDS is the federated ANA registry carrying every
peer's topology, and subscribing to one is a deliberate act. These pages are inventory.

**The WFO name wins** over the DDS name in `reconcile_named`: it is editable via the modify workflow,
so a divergence is deliberate rather than drift.

**Product tags are not derivable from the type name.** The `filterBy: {field: "tag"}` values in
`wfo.py` are whatever the orchestrator's migrations set, and they do not all match the product type:
`TOPOLOGY`, **`SWITCHINGSERVICE`** (no underscore), `STP`, `SDP`, `MDP2P`. A wrong tag is silent —
the query returns an empty page, and the reconciliation renders every DDS entry as `DDS only` with
zero `not in DDS`, which looks like a plausible unsubscribed estate rather than a bug. That exact
asymmetry (N `DDS only`, 0 `not in DDS`) is the signature of a broken WFO-side query, not real drift.
Verify a tag against `select tag from products` rather than assuming; the unit tests mock
`query_wfo`, so they never exercise the tag string.

**Patching accessors**: pages that import an accessor by name are patched on the *page* module
(`patch("amiss.frontend.stp.get_stps")`). `inventory.py` is the exception — its router factory would
capture a directly-passed function at import time, so it calls through the module (`data.get_topologies`)
and its tests patch `amiss.data.<accessor>`. Adding a dashboard fetch also means adding it to
`_DASHBOARD_FETCHES` in `tests/frontend/test_pages.py`, or the unmocked fetch hits the network.

**Every WFO future must be resolved inside `home()`'s `WfoUnauthorizedError` guard.** `_safe` re-raises
a refusal, so a future resolved after the `try` turns a 401 into a 500. The DDS/aggregator futures use
AMISS's own identity and cannot raise it.

The test setup in `conftest.py` creates dummy PEM files (`amiss-certificate.pem`, `amiss-private-key.pem`) **before any amiss imports**, because `Settings` validates its `FilePath` fields at import time. Upstreams are mocked per test (`unittest.mock.patch` for units; the `responses` library for the integration stack in `tests/integration/`).

## Versioning

The version is the git tag; never edit it. `pyproject.toml` is `dynamic = ["version"]` with
setuptools-scm, so a tag builds `0.1.1` and any other commit builds `0.1.2.dev<n>+g<sha>`. The
container build has no `.git`, so `container.yml` resolves the version on the runner and passes
`--build-arg VERSION`, which the `Dockerfile` exports as
`SETUPTOOLS_SCM_PRETEND_VERSION_FOR_NSI_MGMT_INFO`. Omitting it fails the build by design. `uv.lock`
records the project as `(dynamic)` and so does not churn per commit.

## Code style

- Line length: 120
- Formatting and linting: `ruff format` + `ruff check` (ruff is the single tool — black/isort/flake8 removed)
- Python target: 3.13
- mypy with `pydantic.mypy` plugin, `disallow_untyped_defs = true`
- ruff rules: ANN, ARG, B, C, D, E, F, I, N, PGH, PTH, Q, RET, RUF, S, T, W; tests exempt from ANN/S101/docstring rules via `per-file-ignores`
