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

"""Spectrum: the SDPs with the circuits crossing each, built live from WFO SDPs + aggregator paths."""

from enum import Enum

from fastapi import APIRouter
from fastui import AnyComponent, FastUI
from fastui import components as c
from fastui.events import GoToEvent
from pydantic import BaseModel, Field
from starlette.requests import Request

from amiss.data import get_spectrum
from amiss.frontend.util import (
    app_page,
    button_row,
    error_message,
    root_url,
    sort_form,
    sort_rows,
    spectrum_circuit_table,
    spectrum_sdp_table,
    token_from_request,
)

router = APIRouter()


class SpectrumSort(str, Enum):
    sdp_name = "sdp_name"
    stp_a = "stp_a"
    circuit_count = "circuit_count"
    total_capacity = "total_capacity"


class SpectrumSortForm(BaseModel):
    sort: SpectrumSort | None = Field(default=None, title="Sort by")


@router.get("", response_model=FastUI, response_model_exclude_none=True)
def spectrum(request: Request, sort: str | None = None) -> list[AnyComponent]:
    """List the SDPs with the count and capacity of the circuits crossing each."""
    view = get_spectrum(token_from_request(request))
    if view.error:
        return app_page(error_message(view.error), title="Spectrum")
    return app_page(
        sort_form(SpectrumSortForm, root_url("/spectrum"), sort),
        spectrum_sdp_table(sort_rows(view.rows, sort)),
        title="Spectrum",
    )


@router.get("/{subscription_id}/", response_model=FastUI, response_model_exclude_none=True)
def spectrum_detail(request: Request, subscription_id: str) -> list[AnyComponent]:
    """Show the circuits crossing one SDP, re-fetched live by subscription id."""
    view = get_spectrum(token_from_request(request))
    if view.error:
        return app_page(error_message(view.error), title="Spectrum")
    sdp = next((row for row in view.rows if row.subscription_id == subscription_id), None)
    if sdp is None:
        return app_page(title=f"No SDP with id {subscription_id}.")
    heading = f"{sdp.stp_a} <-> {sdp.stp_z}" if sdp.stp_a else (sdp.sdp_name or "")
    return app_page(
        button_row([c.Button(text="Back", on_click=GoToEvent(url=root_url("/spectrum")), class_name="+ ms-2")]),
        c.Heading(text=heading, level=4),
        spectrum_circuit_table(sdp.circuits),
        title=f"SDP {sdp.sdp_name}",
    )
