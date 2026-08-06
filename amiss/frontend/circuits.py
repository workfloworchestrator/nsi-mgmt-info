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
from fastui.components.display import DisplayLookup
from fastui.events import GoToEvent
from pydantic import BaseModel, Field
from starlette.requests import Request

from amiss.data import get_circuit_path, get_circuits
from amiss.frontend.util import (
    app_page,
    button_row,
    circuit_table,
    error_message,
    root_url,
    segment_table,
    sort_form,
    sort_rows,
    token_from_request,
)
from amiss.sources.aggregator import PathSegment
from amiss.sources.wfo import CircuitRow, circuit_state_bucket

router = APIRouter()


class CircuitSort(str, Enum):
    state = "state"
    description = "description"
    start_time = "start_time"
    source = "source"
    dest = "dest"
    created_by = "created_by"


class CircuitSortForm(BaseModel):
    sort: CircuitSort | None = Field(default=None, title="Sort by")


# (tab key, label, path). The path doubles as the sort form's submit_url so sorting stays in-tab.
CIRCUIT_TABS = (
    ("activated", "Activated", "/circuits"),
    ("failed", "Failed", "/circuits/failed"),
    ("terminated", "Terminated", "/circuits/terminated"),
    ("all", "All", "/circuits/all"),
)


def _in_tab(circuit: CircuitRow, tab: str) -> bool:
    """Whether a circuit belongs in the given tab (the 'all' tab holds everything)."""
    return tab == "all" or circuit_state_bucket(circuit.state) == tab


def _tabs() -> AnyComponent:
    # FastUI marks the active tab by matching each link's `active` pattern against the current URL.
    return c.LinkList(
        links=[
            c.Link(
                components=[c.Text(text=label)],
                on_click=GoToEvent(url=root_url(path)),
                # the base path would prefix-match every tab, so match it exactly
                active=(root_url(path) if path == "/circuits" else f"startswith:{root_url(path)}"),
            )
            for _key, label, path in CIRCUIT_TABS
        ],
        mode="tabs",
        class_name="+ mb-4",
    )


def _tab_path(tab: str) -> str:
    return next(path for key, _label, path in CIRCUIT_TABS if key == tab)


def _circuits_view(request: Request, tab: str, sort: str | None) -> list[AnyComponent]:
    path = _tab_path(tab)
    rows = get_circuits(token_from_request(request))
    if rows is None:
        return app_page(
            _tabs(),
            error_message("Circuits unavailable: the WFO could not be reached."),
            title="Circuits",
        )
    circuits_in_tab = sort_rows([row for row in rows if _in_tab(row, tab)], sort)
    return app_page(
        _tabs(),
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


@router.get("/{subscription_id}/", response_model=FastUI, response_model_exclude_none=True)
def circuit_details(request: Request, subscription_id: str) -> list[AnyComponent]:
    """Display a single circuit (WFO), re-fetched live by subscription id, plus its aggregator path."""
    rows = get_circuits(token_from_request(request)) or []
    circuit = next((row for row in rows if row.subscription_id == subscription_id), None)
    if circuit is None:
        return app_page(title=f"No circuit with id {subscription_id}.")
    path = get_circuit_path(circuit.connection_id) if circuit.connection_id else []
    # detail shows every field except the list-only helpers (short_id, and the merged source/dest —
    # the raw source_stp/source_vlan/dest_stp/dest_vlan are shown instead). CircuitRow.created_by_name
    # is likewise list-only and needs no exclusion here: model_fields holds no computed fields.
    list_only = {"short_id", "source", "dest"}
    detail_fields = [DisplayLookup(field=name) for name in CircuitRow.model_fields if name not in list_only]
    return app_page(
        button_row([c.Button(text="Back", on_click=GoToEvent(url=root_url("/circuits")), class_name="+ ms-2")]),
        c.Details(data=circuit, fields=detail_fields),
        c.Heading(text="Path", level=4),
        _path_section(path),
        title=f"Circuit {circuit.description}",
    )
