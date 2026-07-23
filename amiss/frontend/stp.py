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

from amiss.data import get_stps
from amiss.frontend.util import (
    app_page,
    button_row,
    error_message,
    root_url,
    sort_form,
    sort_rows,
    stp_table,
    token_from_request,
)
from amiss.sources.reconcile import StpRow

router = APIRouter()


class StpSort(str, Enum):
    status = "status"
    stp_id = "stp_id"
    description = "description"
    switching_service_id = "switching_service_id"
    subscription_id = "subscription_id"


class StpSortForm(BaseModel):
    sort: StpSort | None = Field(default=None, title="Sort by")


@router.get("", response_model=FastUI, response_model_exclude_none=True)
def stp(request: Request, sort: str | None = None) -> list[AnyComponent]:
    """Display STP subscriptions reconciled against the DDS topology."""
    result = get_stps(token_from_request(request))
    if result.error:
        return app_page(error_message(result.error), title="Service Termination Points")
    return app_page(
        sort_form(StpSortForm, root_url("/stp"), sort),
        stp_table(sort_rows(result.rows, sort)),
        title="Service Termination Points",
    )


@router.get("/{stp_id}/", response_model=FastUI, response_model_exclude_none=True)
def stp_details(request: Request, stp_id: str) -> list[AnyComponent]:
    """Display a single STP, re-fetched live by its normalized id, with all fields incl. the switching service."""
    result = get_stps(token_from_request(request))
    if result.error:
        return app_page(error_message(result.error), title="Service Termination Points")
    row = next((row for row in result.rows if row.stp_id == stp_id), None)
    if row is None:
        return app_page(title=f"No STP with id {stp_id}.")
    detail_fields = [DisplayLookup(field=name) for name in StpRow.model_fields]
    return app_page(
        button_row([c.Button(text="Back", on_click=GoToEvent(url=root_url("/stp")), class_name="+ ms-2")]),
        c.Details(data=row, fields=detail_fields),
        title=f"STP {row.stp_id}",
    )
