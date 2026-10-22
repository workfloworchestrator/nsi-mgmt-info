# Copyright 2026 SURF.
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
from typing import Literal, get_args

from fastapi import APIRouter
from fastui import AnyComponent, FastUI
from fastui import components as c
from pydantic import BaseModel, Field
from starlette.requests import Request

from amiss.data import get_provider_detail, get_providers
from amiss.frontend.util import (
    Tabs,
    app_page,
    back_button,
    detail_fields,
    error_message,
    provider_reservation_table,
    provider_table,
    root_url,
    sort_form,
    sort_rows,
    tab_links,
    token_from_request,
)
from amiss.sources.providers import ProviderReservationRow, ProviderRow, reservation_tab

router = APIRouter()


class ProviderSort(str, Enum):
    name = "name"
    nsa_id = "nsa_id"
    provider_url = "provider_url"


class ProviderSortForm(BaseModel):
    sort: ProviderSort | None = Field(default=None, title="Sort by")


@router.get("", response_model=FastUI, response_model_exclude_none=True)
def providers(sort: str | None = None) -> list[AnyComponent]:
    """Display the uPAs the aggregator peers with."""
    title = "Providers"
    result = get_providers()
    if result.error:
        return app_page(error_message(result.error), title=title)
    return app_page(
        sort_form(ProviderSortForm, root_url("/providers"), sort),
        provider_table(sort_rows(result.rows, sort)),
        title=title,
    )


ReservationTab = Literal["active", "terminated", "all"]


def _reservation_tabs(nsa_id: str) -> Tabs:
    """Build the reservation tabs; the default (active) tab is the detail page's own path."""
    base = f"/providers/{nsa_id}/"
    return tuple((tab, tab.title(), base if tab == "active" else f"{base}{tab}") for tab in get_args(ReservationTab))


def _reservations_section(reservations: list[ProviderReservationRow] | None, tab: ReservationTab) -> AnyComponent:
    """Render the provider's reservations in one tab, distinguishing 'could not fetch' from 'none'."""
    if reservations is None:
        return error_message("Reservations unavailable: the provider could not be reached.")
    rows = [row for row in reservations if tab == "all" or reservation_tab(row) == tab]
    return provider_reservation_table(rows) if rows else c.Markdown(text="_No reservations in this tab._")


@router.get("/{nsa_id}/", response_model=FastUI, response_model_exclude_none=True)
@router.get("/{nsa_id}/{tab}", response_model=FastUI, response_model_exclude_none=True)
def provider_details(request: Request, nsa_id: str, tab: ReservationTab = "active") -> list[AnyComponent]:
    """Display a single provider and its reservations in one lifecycle tab, queried live from the uPA."""
    detail = get_provider_detail(token_from_request(request), nsa_id)
    if detail.error:
        return app_page(error_message(detail.error), title="Provider")
    if detail.provider is None:
        return app_page(title=f"No provider with id {nsa_id}.")
    return app_page(
        back_button("/providers"),
        c.Details(data=detail.provider, fields=detail_fields(ProviderRow)),
        c.Heading(text="Reservations", level=4),
        tab_links(_reservation_tabs(nsa_id)),
        _reservations_section(detail.reservations, tab),
        title=f"Provider {detail.provider.name}",
    )
