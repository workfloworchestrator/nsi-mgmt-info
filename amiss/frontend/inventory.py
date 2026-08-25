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

"""The /topology and /switching-service reconciliation pages."""

from collections.abc import Callable
from enum import Enum

from fastapi import APIRouter
from fastui import AnyComponent, FastUI
from pydantic import BaseModel, Field
from starlette.requests import Request

from amiss import data
from amiss.frontend.util import (
    app_page,
    error_message,
    in_tab,
    named_table,
    reconcile_tabs,
    root_url,
    sort_form,
    sort_rows,
    tab_links,
    tab_path,
    token_from_request,
)
from amiss.sources.reconcile import NamedReconciliation


class NamedSort(str, Enum):
    status = "status"
    object_id = "object_id"
    description = "description"


class NamedSortForm(BaseModel):
    sort: NamedSort | None = Field(default=None, title="Sort by")


def _build_router(
    base: str, title: str, id_title: str, get_rows: Callable[[str | None], NamedReconciliation]
) -> APIRouter:
    """Build the four tab routes of one reconciliation page."""
    router = APIRouter()
    tabs = reconcile_tabs(base)

    def view(request: Request, tab: str, sort: str | None) -> list[AnyComponent]:
        result = get_rows(token_from_request(request))
        if result.error:
            return app_page(tab_links(tabs), error_message(result.error), title=title)
        rows = sort_rows([row for row in result.rows if in_tab(row, tab)], sort)
        return app_page(
            tab_links(tabs),
            sort_form(NamedSortForm, root_url(tab_path(tabs, tab)), sort),
            named_table(rows, id_title),
            title=title,
        )

    @router.get("", response_model=FastUI, response_model_exclude_none=True)
    def index(request: Request, sort: str | None = None) -> list[AnyComponent]:
        return view(request, "all", sort)

    @router.get("/backed", response_model=FastUI, response_model_exclude_none=True)
    def backed(request: Request, sort: str | None = None) -> list[AnyComponent]:
        return view(request, "in_both", sort)

    @router.get("/missing", response_model=FastUI, response_model_exclude_none=True)
    def missing(request: Request, sort: str | None = None) -> list[AnyComponent]:
        return view(request, "missing_in_dds", sort)

    @router.get("/dds-only", response_model=FastUI, response_model_exclude_none=True)
    def dds_only(request: Request, sort: str | None = None) -> list[AnyComponent]:
        return view(request, "dds_only", sort)

    return router


# Called through the module, not bound here: _build_router captures its argument once. See CLAUDE.md.
topology_router = _build_router("/topology", "Topologies", "Topology ID", lambda token: data.get_topologies(token))
switching_service_router = _build_router(
    "/switching-service",
    "Switching Services",
    "Switching Service ID",
    lambda token: data.get_switching_services(token),
)
