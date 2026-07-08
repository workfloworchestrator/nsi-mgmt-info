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
from fastui.events import GoToEvent
from pydantic import BaseModel, Field
from starlette.requests import Request

from amiss.data import get_circuits
from amiss.frontend.util import (
    app_page,
    button_row,
    circuit_table,
    error_message,
    sort_form,
    sort_rows,
    token_from_request,
)

router = APIRouter()


class CircuitSort(str, Enum):
    state = "state"
    description = "description"
    start_time = "start_time"
    source_stp = "source_stp"
    dest_stp = "dest_stp"
    created_by = "created_by"


class CircuitSortForm(BaseModel):
    sort: CircuitSort | None = Field(default=None, title="Sort by")


@router.get("", response_model=FastUI, response_model_exclude_none=True)
def circuits(request: Request, sort: str | None = None) -> list[AnyComponent]:
    """Display all MDP2P circuits, sourced live from the WFO."""
    rows = get_circuits(token_from_request(request))
    if rows is None:
        return app_page(error_message("Circuits unavailable: the WFO could not be reached."), title="Circuits")
    return app_page(
        sort_form(CircuitSortForm, "/circuits", sort),
        circuit_table(sort_rows(rows, sort)),
        title="Circuits",
    )


@router.get("/{subscription_id}/", response_model=FastUI, response_model_exclude_none=True)
def circuit_details(request: Request, subscription_id: str) -> list[AnyComponent]:
    """Display details of a single circuit, re-fetched live by subscription id."""
    rows = get_circuits(token_from_request(request)) or []
    circuit = next((row for row in rows if row.subscription_id == subscription_id), None)
    if circuit is None:
        return app_page(title=f"No circuit with id {subscription_id}.")
    return app_page(
        button_row([c.Button(text="Back", on_click=GoToEvent(url="/circuits"), class_name="+ ms-2")]),
        c.Details(data=circuit),
        title=f"Circuit {circuit.description}",
    )
