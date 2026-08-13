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

from amiss.data import get_sdp_detail, get_sdps
from amiss.frontend.util import (
    app_page,
    back_button,
    detail_fields,
    error_message,
    in_tab,
    reconcile_tabs,
    root_url,
    sdp_table,
    sort_form,
    sort_rows,
    spectrum_circuit_table,
    tab_links,
    tab_path,
    token_from_request,
)
from amiss.sources.aggregator import SpectrumView
from amiss.sources.reconcile import SdpRow

router = APIRouter()

SDP_TABS = reconcile_tabs("/sdp")


class SdpSort(str, Enum):
    status = "status"
    stp_a_name = "stp_a_name"
    stp_z_name = "stp_z_name"
    description = "description"
    capacity = "capacity"


class SdpSortForm(BaseModel):
    sort: SdpSort | None = Field(default=None, title="Sort by")


def _sdp_view(request: Request, tab: str, sort: str | None) -> list[AnyComponent]:
    title = "Service Demarcation Points"
    result = get_sdps(token_from_request(request))
    if result.error:
        return app_page(tab_links(SDP_TABS), error_message(result.error), title=title)
    rows = sort_rows([row for row in result.rows if in_tab(row, tab)], sort)
    return app_page(
        tab_links(SDP_TABS),
        sort_form(SdpSortForm, root_url(tab_path(SDP_TABS, tab)), sort),
        sdp_table(rows),
        title=title,
    )


# The tab routes are literals and must be declared before /{subscription_id}/, or an id could match one.
@router.get("", response_model=FastUI, response_model_exclude_none=True)
def sdp(request: Request, sort: str | None = None) -> list[AnyComponent]:
    """Display every SDP subscription reconciled against the DDS topology."""
    return _sdp_view(request, "all", sort)


@router.get("/backed", response_model=FastUI, response_model_exclude_none=True)
def sdp_backed(request: Request, sort: str | None = None) -> list[AnyComponent]:
    """SDPs present in both the WFO and the DDS."""
    return _sdp_view(request, "in_both", sort)


@router.get("/missing", response_model=FastUI, response_model_exclude_none=True)
def sdp_missing(request: Request, sort: str | None = None) -> list[AnyComponent]:
    """SDP subscriptions the DDS no longer advertises."""
    return _sdp_view(request, "missing_in_dds", sort)


@router.get("/dds-only", response_model=FastUI, response_model_exclude_none=True)
def sdp_dds_only(request: Request, sort: str | None = None) -> list[AnyComponent]:
    """SDPs the DDS knows but that have no subscription yet."""
    return _sdp_view(request, "dds_only", sort)


def _circuits_section(spectrum: SpectrumView, subscription_id: str) -> AnyComponent:
    """Render the circuits crossing this SDP, distinguishing 'could not fetch' from 'none'."""
    if spectrum.error:
        return error_message(spectrum.error)
    row = next((r for r in spectrum.rows if r.subscription_id == subscription_id), None)
    if row is None or not row.circuits:
        return c.Markdown(text="_No circuits cross this SDP._")
    return spectrum_circuit_table(row.circuits)


@router.get("/{subscription_id}/", response_model=FastUI, response_model_exclude_none=True)
def sdp_details(request: Request, subscription_id: str) -> list[AnyComponent]:
    """Display a single SDP subscription and the circuits crossing it."""
    sdps, spectrum = get_sdp_detail(token_from_request(request))
    if sdps.error:
        return app_page(error_message(sdps.error), title="Service Demarcation Point")
    row = next((r for r in sdps.rows if r.subscription_id == subscription_id), None)
    if row is None:
        return app_page(title=f"No SDP with id {subscription_id}.")
    return app_page(
        back_button("/sdp"),
        c.Details(data=row, fields=detail_fields(SdpRow)),
        c.Heading(text="Circuits on this SDP", level=4),
        _circuits_section(spectrum, subscription_id),
        title=f"SDP {row.description or subscription_id}",
    )
