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

from amiss.data import CircuitList, get_stp_detail, get_stps
from amiss.frontend.util import (
    app_page,
    back_button,
    circuit_table,
    detail_fields,
    error_message,
    in_tab,
    reconcile_tabs,
    root_url,
    sort_form,
    sort_rows,
    stp_table,
    tab_links,
    tab_path,
    token_from_request,
)
from amiss.sources.reconcile import StpRow, normalize_id
from amiss.sources.wfo import CircuitRow, is_terminated

router = APIRouter()

STP_TABS = reconcile_tabs("/stp")


class StpSort(str, Enum):
    status = "status"
    stp_id = "stp_id"
    description = "description"
    capacity = "capacity"


class StpSortForm(BaseModel):
    sort: StpSort | None = Field(default=None, title="Sort by")


def _stp_view(request: Request, tab: str, sort: str | None) -> list[AnyComponent]:
    title = "Service Termination Points"
    result = get_stps(token_from_request(request))
    if result.error:
        return app_page(tab_links(STP_TABS), error_message(result.error), title=title)
    rows = sort_rows([row for row in result.rows if in_tab(row, tab)], sort)
    return app_page(
        tab_links(STP_TABS),
        sort_form(StpSortForm, root_url(tab_path(STP_TABS, tab)), sort),
        stp_table(rows),
        title=title,
    )


# The tab routes are literals and must be declared before /{subscription_id}/, or an id could match one.
@router.get("", response_model=FastUI, response_model_exclude_none=True)
def stp(request: Request, sort: str | None = None) -> list[AnyComponent]:
    """Display every STP subscription reconciled against the DDS topology."""
    return _stp_view(request, "all", sort)


@router.get("/backed", response_model=FastUI, response_model_exclude_none=True)
def stp_backed(request: Request, sort: str | None = None) -> list[AnyComponent]:
    """STPs present in both the WFO and the DDS."""
    return _stp_view(request, "in_both", sort)


@router.get("/missing", response_model=FastUI, response_model_exclude_none=True)
def stp_missing(request: Request, sort: str | None = None) -> list[AnyComponent]:
    """STP subscriptions the DDS no longer advertises."""
    return _stp_view(request, "missing_in_dds", sort)


@router.get("/dds-only", response_model=FastUI, response_model_exclude_none=True)
def stp_dds_only(request: Request, sort: str | None = None) -> list[AnyComponent]:
    """STPs the DDS knows but that have no subscription yet."""
    return _stp_view(request, "dds_only", sort)


def _circuits_on_stp(circuits: list[CircuitRow], stp_id: str | None) -> list[CircuitRow]:
    """Return the circuits still using this STP, on either end.

    Matched on the endpoint's STP *id*: the circuit table shows the STP's name, which is display text
    and would match nothing here. Terminated circuits are left out — the question this list answers is
    what the port is carrying now, and history only obscures it.
    """
    target = normalize_id(stp_id)
    if target is None:
        return []
    return [
        circuit
        for circuit in circuits
        if not is_terminated(circuit.state)
        and target in {normalize_id(circuit.source_stp_id), normalize_id(circuit.dest_stp_id)}
    ]


def _circuits_section(circuits: CircuitList, row: StpRow) -> AnyComponent:
    """Render the circuits on this STP, distinguishing 'could not fetch' from 'none'."""
    if circuits.error:
        return error_message(circuits.error)
    on_stp = _circuits_on_stp(circuits.rows, row.stp_id)
    return circuit_table(on_stp) if on_stp else c.Markdown(text="_No circuits currently use this STP._")


@router.get("/{subscription_id}/", response_model=FastUI, response_model_exclude_none=True)
def stp_details(request: Request, subscription_id: str) -> list[AnyComponent]:
    """Display a single STP subscription and the circuits terminating on it."""
    stps, circuits = get_stp_detail(token_from_request(request))
    if stps.error:
        return app_page(error_message(stps.error), title="Service Termination Point")
    row = next((r for r in stps.rows if r.subscription_id == subscription_id), None)
    if row is None:
        return app_page(title=f"No STP with id {subscription_id}.")
    return app_page(
        back_button("/stp"),
        c.Details(data=row, fields=detail_fields(StpRow)),
        c.Heading(text="Circuits on this STP", level=4),
        _circuits_section(circuits, row),
        title=f"STP {row.stp_id}",
    )
