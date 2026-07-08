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
from concurrent.futures import ThreadPoolExecutor
from enum import Enum

from fastapi import APIRouter
from fastui import AnyComponent, FastUI
from fastui import components as c
from fastui.events import GoToEvent
from starlette.requests import Request

from amiss.data import get_circuits, get_sdps, get_stps
from amiss.frontend.util import app_page, token_from_request
from amiss.sources.reconcile import ReconcileStatus, SdpReconciliation, StpReconciliation
from amiss.sources.wfo import CircuitRow, circuit_state_bucket

router = APIRouter()

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
        on_click=GoToEvent(url=url),
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
    return _card("Circuits", "/circuits", len(circuits), lines, unavailable=False)


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


def _link_card(title: str, url: str, subtitle: str) -> AnyComponent:
    """Build a card with no counts, just a title and subtitle linking to a page."""
    return c.Link(
        components=[
            c.Div(
                components=[
                    c.Heading(text=title, level=5, class_name="+ card-title"),
                    _muted(subtitle, "+ small text-muted"),
                ],
                class_name="+ card-body",
            )
        ],
        on_click=GoToEvent(url=url),
        class_name=_CARD_CLASS,
    )


@router.get("/", response_model=FastUI, response_model_exclude_none=True)
def home(request: Request) -> list[AnyComponent]:
    """Dashboard: a summary card per section, each linking to its tab; sources fetched live.

    The three source fetches are independent and each does blocking HTTP, so they run concurrently
    (wall-clock = the slowest one, not the sum); the accessors never raise, so results collect safely.
    """
    token = token_from_request(request)
    with ThreadPoolExecutor(max_workers=3) as pool:
        circuits = pool.submit(get_circuits, token)
        stps = pool.submit(get_stps, token)
        sdps = pool.submit(get_sdps, token)
    cards = [
        _circuit_card(circuits.result()),
        _reconcile_card("Termination Points", "/stp", stps.result()),
        _reconcile_card("Demarcation Points", "/sdp", sdps.result()),
        _link_card("Spectrum", "/spectrum/active", "Active circuits per link"),
    ]
    dashboard = c.Div(
        components=[c.Div(components=[card], class_name="+ col-12 col-md-3 mb-3") for card in cards],
        class_name="+ row",
    )
    return app_page(c.Markdown(text=introduction), dashboard, title="Dashboard")
