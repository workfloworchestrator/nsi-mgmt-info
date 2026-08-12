# Copyright 2024-2026 SURF.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from typing import TypeVar

import structlog
from fastapi import APIRouter
from fastui import AnyComponent, FastUI
from fastui import components as c
from fastui.events import GoToEvent
from starlette.requests import Request

from amiss.data import NOT_AUTHORIZED
from amiss.frontend.util import app_page, error_message, root_url, token_from_request
from amiss.sources.aggregator import UNATTRIBUTED_ID, SpectrumView, build_spectrum, fetch_agg_circuits
from amiss.sources.dds_topology import fetch_dds_sdps, fetch_dds_stps
from amiss.sources.reconcile import (
    ReconcileStatus,
    SdpReconciliation,
    StpReconciliation,
    reconcile_sdps,
    reconcile_stps,
)
from amiss.sources.wfo import (
    CircuitRow,
    WfoUnauthorizedError,
    circuit_state_bucket,
    fetch_circuits,
    fetch_sdp_subscriptions,
    fetch_stp_subscriptions,
)

logger = structlog.get_logger(__name__)
router = APIRouter()

_T = TypeVar("_T")


def _safe(fn: Callable[..., _T], *args: object) -> _T | None:
    """Run a source fetch, degrading any unexpected error to ``None`` so the dashboard never 500s.

    A refused credential is let through: it makes every card read "unavailable", which is the very
    misdiagnosis the pages avoid, and the dashboard is where a blocked user lands first.
    """
    try:
        return fn(*args)
    except WfoUnauthorizedError:
        raise
    except Exception as e:
        logger.warning("dashboard source fetch failed", fn=fn.__name__, error=str(e))
        return None


introduction = """
[AMISS](https://github.com/workfloworchestrator/nsi-mgmt-info/),
the Network Service Interface (NSI) Management Information System (MIS)
for the [Advanced North Atlantic (ANA) consortium](https://www.anaeng.global/).
This is part of a project called ANA-GRAM, the ANA Global Resource Aggregation Method,
to federate and manage the ANA trans-Atlantic links via network automation.
"""

_CARD_CLASS = "+ card h-100 text-decoration-none text-reset shadow-sm"


class Tone(str, Enum):
    """How prominently a breakdown line is shown."""

    GOOD = "good"  # the healthy counter (green): Activated / backed by DDS
    BAD = "bad"  # the attention counter (red when > 0): Failed / not in DDS
    NEUTRAL = "neutral"  # nice-to-know (muted): Terminated / DDS only


def _muted(text: str, class_name: str) -> AnyComponent:
    """Wrap text in a Div because FastUI's Text component takes no class_name."""
    return c.Div(components=[c.Text(text=text)], class_name=class_name)


def _stat_line(label: str, count: int, tone: Tone) -> AnyComponent:
    """Render a 'label: count' line, coloured by tone (bad only reddens when count > 0)."""
    match tone:
        case Tone.GOOD:
            class_name = "+ small text-success fw-semibold"
        case Tone.BAD:
            class_name = "+ small text-danger fw-semibold" if count else "+ small text-muted"
        case _:
            class_name = "+ small text-muted"
    return _muted(f"{label}: {count}", class_name)


def _card(
    title: str, url: str, headline: int | None, lines: list[tuple[str, int, Tone]], *, unavailable: bool
) -> AnyComponent:
    """Build a clickable summary card: title, headline count, and a tone-coloured breakdown (or 'unavailable')."""
    body: list[AnyComponent] = [c.Heading(text=title, level=5, class_name="+ card-title")]
    if unavailable:
        body.append(_muted("unavailable", "+ text-muted fst-italic"))
    else:
        body.append(_muted(str(headline), "+ display-6 fw-bold mb-2"))
        body.extend(_stat_line(label, count, tone) for label, count, tone in lines)
    return c.Link(
        components=[c.Div(components=body, class_name="+ card-body")],
        on_click=GoToEvent(url=root_url(url)),
        class_name=_CARD_CLASS,
    )


def _circuit_card(circuits: list[CircuitRow] | None) -> AnyComponent:
    if circuits is None:
        return _card("Circuits", "/circuits", None, [], unavailable=True)
    buckets = Counter(circuit_state_bucket(circuit.state) for circuit in circuits)
    lines = [
        ("Activated", buckets["activated"], Tone.GOOD),
        ("Failed", buckets["failed"], Tone.BAD),
        ("Terminated", buckets["terminated"], Tone.NEUTRAL),
    ]
    # The headline counts the circuits that still exist; terminated ones stay in the breakdown only,
    # or the number would keep climbing with history and never reflect the current estate.
    return _card("Circuits", "/circuits", len(circuits) - buckets["terminated"], lines, unavailable=False)


def _reconcile_card(title: str, url: str, result: StpReconciliation | SdpReconciliation) -> AnyComponent:
    if result.error:
        return _card(title, url, None, [], unavailable=True)
    counts = Counter(row.status for row in result.rows)
    lines = [
        ("backed by DDS", counts[ReconcileStatus.IN_BOTH], Tone.GOOD),
        ("not in DDS", counts[ReconcileStatus.MISSING_IN_DDS], Tone.BAD),
        ("DDS only", counts[ReconcileStatus.DDS_ONLY], Tone.NEUTRAL),
    ]
    return _card(title, url, len(result.rows), lines, unavailable=False)


def _spectrum_card(view: SpectrumView) -> AnyComponent:
    if view.error:
        return _card("Spectrum", "/spectrum", None, [], unavailable=True)
    sdps = [row for row in view.rows if row.subscription_id != UNATTRIBUTED_ID]
    unattributed = next((row.circuit_count for row in view.rows if row.subscription_id == UNATTRIBUTED_ID), 0)
    lines = [
        ("SDPs in use", sum(1 for row in sdps if row.circuit_count), Tone.GOOD),
        ("unattributed circuits", unattributed, Tone.BAD),
        ("idle SDPs", sum(1 for row in sdps if not row.circuit_count), Tone.NEUTRAL),
    ]
    return _card("Spectrum", "/spectrum", len(sdps), lines, unavailable=False)


@router.get("/", response_model=FastUI, response_model_exclude_none=True)
def home(request: Request) -> list[AnyComponent]:
    """Dashboard: a summary card per section, sources fetched live.

    Each upstream is fetched exactly once, all concurrently (blocking HTTP releases the GIL), then the
    cards are composed from the shared results via the same pure builders the pages use. Fetching once
    (vs. per-card accessors that each re-fetch) removes duplicate WFO queries and gives every card a
    single consistent snapshot; wall-clock is the slowest single fetch, not their sum.
    """
    token = token_from_request(request)
    with ThreadPoolExecutor(max_workers=6) as pool:
        circuits = pool.submit(_safe, fetch_circuits, token)
        stp_subs = pool.submit(_safe, fetch_stp_subscriptions, token)
        sdp_subs = pool.submit(_safe, fetch_sdp_subscriptions, token)
        dds_stps = pool.submit(_safe, fetch_dds_stps)
        dds_sdps = pool.submit(_safe, fetch_dds_sdps)
        agg = pool.submit(_safe, fetch_agg_circuits)
    try:
        circuit_rows, sdp_rows = circuits.result(), sdp_subs.result()
    except WfoUnauthorizedError:
        return app_page(c.Markdown(text=introduction), error_message(NOT_AUTHORIZED), title="Dashboard")
    cards = [
        _circuit_card(circuit_rows),
        _reconcile_card("Termination Points", "/stp", reconcile_stps(stp_subs.result(), dds_stps.result())),
        _reconcile_card("Demarcation Points", "/sdp", reconcile_sdps(sdp_rows, dds_sdps.result())),
        _spectrum_card(build_spectrum(sdp_rows, agg.result(), circuit_rows)),
    ]
    dashboard = c.Div(
        components=[c.Div(components=[card], class_name="+ col-12 col-md-3 mb-3") for card in cards],
        class_name="+ row",
    )
    return app_page(c.Markdown(text=introduction), dashboard, title="Dashboard")
