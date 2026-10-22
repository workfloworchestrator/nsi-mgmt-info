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

from enum import Enum

from fastapi import APIRouter
from fastui import AnyComponent, FastUI
from fastui import components as c
from pydantic import BaseModel, Field
from starlette.requests import Request

from amiss.data import get_circuit_detail, get_circuits
from amiss.frontend.util import (
    app_page,
    circuit_table,
    detail_buttons,
    detail_fields,
    error_message,
    root_url,
    segment_table,
    sort_form,
    sort_rows,
    spectrum_sdp_table,
    tab_links,
    tab_path,
    token_from_request,
)
from amiss.sources.aggregator import PathSegment, SpectrumRow
from amiss.sources.wfo import CircuitRow, circuit_state_bucket

router = APIRouter()


class CircuitSort(str, Enum):
    state = "state"
    description = "description"
    start_time = "start_time"
    source = "source"
    dest = "dest"
    bandwidth = "bandwidth"
    created_by = "created_by"


class CircuitSortForm(BaseModel):
    sort: CircuitSort | None = Field(default=None, title="Sort by")


CIRCUIT_TABS = (
    ("activated", "Activated", "/circuits"),
    ("failed", "Failed", "/circuits/failed"),
    ("reserved", "Reserved", "/circuits/reserved"),
    ("terminated", "Terminated", "/circuits/terminated"),
    ("all", "All", "/circuits/all"),
)


def _in_tab(circuit: CircuitRow, tab: str) -> bool:
    """Whether a circuit belongs in the given tab (the 'all' tab holds everything)."""
    return tab == "all" or circuit_state_bucket(circuit.state) == tab


def _circuits_view(request: Request, tab: str, sort: str | None) -> list[AnyComponent]:
    path = tab_path(CIRCUIT_TABS, tab)
    result = get_circuits(token_from_request(request))
    if result.error:
        return app_page(tab_links(CIRCUIT_TABS), error_message(result.error), title="Circuits")
    circuits_in_tab = sort_rows([row for row in result.rows if _in_tab(row, tab)], sort)
    return app_page(
        tab_links(CIRCUIT_TABS),
        sort_form(CircuitSortForm, root_url(path), sort),
        circuit_table(circuits_in_tab),
        title="Circuits",
    )


@router.get("", response_model=FastUI, response_model_exclude_none=True)
def circuits(request: Request, sort: str | None = None) -> list[AnyComponent]:
    """Circuits that are neither failed nor terminated (default tab)."""
    return _circuits_view(request, "activated", sort)


@router.get("/failed", response_model=FastUI, response_model_exclude_none=True)
def circuits_failed(request: Request, sort: str | None = None) -> list[AnyComponent]:
    """Circuits in the FAILED state."""
    return _circuits_view(request, "failed", sort)


@router.get("/reserved", response_model=FastUI, response_model_exclude_none=True)
def circuits_reserved(request: Request, sort: str | None = None) -> list[AnyComponent]:
    """Circuits in the RESERVED state."""
    return _circuits_view(request, "reserved", sort)


@router.get("/terminated", response_model=FastUI, response_model_exclude_none=True)
def circuits_terminated(request: Request, sort: str | None = None) -> list[AnyComponent]:
    """Circuits in the TERMINATED state."""
    return _circuits_view(request, "terminated", sort)


@router.get("/all", response_model=FastUI, response_model_exclude_none=True)
def circuits_all(request: Request, sort: str | None = None) -> list[AnyComponent]:
    """All circuits regardless of state."""
    return _circuits_view(request, "all", sort)


def _path_section(path: list[PathSegment] | None) -> AnyComponent:
    """Render the circuit's aggregator path: a table, or a note distinguishing 'unreachable' from 'none'."""
    if path is None:
        return error_message("Path unavailable: the aggregator proxy could not be reached.")
    if not path:
        return c.Markdown(text="_No path segments reported for this circuit._")
    return segment_table(path)


def _sdps_section(sdps: list[SpectrumRow] | None) -> AnyComponent:
    """Render the SDPs the circuit crosses, distinguishing 'could not work out' from 'none'."""
    if sdps is None:
        return error_message("SDPs unavailable: the aggregator proxy or WFO could not be reached.")
    return spectrum_sdp_table(sdps) if sdps else c.Markdown(text="_This circuit crosses no known SDP._")


def _failure_banner(circuit: CircuitRow) -> list[AnyComponent]:
    """Why a failed circuit failed, shown above its details; the field stays in the details either way."""
    if circuit_state_bucket(circuit.state) != "failed" or not circuit.last_error:
        return []
    return [c.Div(components=[c.Text(text=circuit.last_error)], class_name="+ alert alert-danger")]


_CIRCUIT_LINKS = {
    "source_stp": "/stp/{source_stp_subscription_id}/",
    "dest_stp": "/stp/{dest_stp_subscription_id}/",
}


@router.get("/{subscription_id}/", response_model=FastUI, response_model_exclude_none=True)
def circuit_details(request: Request, subscription_id: str) -> list[AnyComponent]:
    """Display a single circuit (WFO), re-fetched live by subscription id, plus its path and the SDPs it crosses."""
    detail = get_circuit_detail(token_from_request(request), subscription_id)
    if detail.error:
        return app_page(error_message(detail.error), title="Circuit")
    circuit = detail.circuit
    if circuit is None:
        return app_page(title=f"No circuit with id {subscription_id}.")
    # the merged source/dest are list-only; the detail shows the raw stp/vlan fields instead
    fields = detail_fields(CircuitRow, exclude={"source", "dest"}, links=_CIRCUIT_LINKS)
    return app_page(
        detail_buttons("/circuits", "circuits", subscription_id),
        *_failure_banner(circuit),
        c.Details(data=circuit, fields=fields),
        c.Heading(text="Path", level=4),
        _path_section(detail.path),
        c.Heading(text="SDPs crossed", level=4),
        _sdps_section(detail.sdps),
        title=f"Circuit {circuit.description}",
    )
