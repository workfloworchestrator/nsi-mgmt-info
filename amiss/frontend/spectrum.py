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
from pydantic import BaseModel, Field
from starlette.requests import Request

from amiss.data import get_spectrum
from amiss.frontend.util import (
    app_page,
    error_message,
    root_url,
    sort_form,
    sort_rows,
    spectrum_circuit_table,
    spectrum_sdp_table,
    token_from_request,
)
from amiss.sources.aggregator import SpectrumRow, split_unattributed

router = APIRouter()


class SpectrumSort(str, Enum):
    sdp_name = "sdp_name"
    stp_a = "stp_a"
    stp_z = "stp_z"
    circuit_count = "circuit_count"
    total_capacity = "total_capacity"
    utilisation = "utilisation"


class SpectrumSortForm(BaseModel):
    sort: SpectrumSort | None = Field(default=None, title="Sort by")


def _unattributed_section(row: SpectrumRow | None) -> list[AnyComponent]:
    """List the circuits that cross no known SDP, if any.

    They have no SDP subscription to drill into, so they are shown here rather than behind a link
    that would have nowhere to point.
    """
    if row is None:
        return []
    return [
        c.Heading(text="Unattributed circuits", level=4),
        c.Markdown(text="_Multi-domain circuits whose path crosses no SDP known to the WFO._"),
        spectrum_circuit_table(row.circuits),
    ]


@router.get("", response_model=FastUI, response_model_exclude_none=True)
def spectrum(request: Request, sort: str | None = None) -> list[AnyComponent]:
    """List the SDPs with the count, reserved capacity and utilisation of the circuits crossing each."""
    view = get_spectrum(token_from_request(request))
    if view.error:
        return app_page(error_message(view.error), title="Spectrum")
    sdps, unattributed = split_unattributed(view.rows)
    return app_page(
        sort_form(SpectrumSortForm, root_url("/spectrum"), sort),
        spectrum_sdp_table(sort_rows(sdps, sort)),
        *_unattributed_section(unattributed),
        title="Spectrum",
    )
