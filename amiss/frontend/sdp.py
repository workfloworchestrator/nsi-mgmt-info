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

from fastapi import APIRouter
from fastui import AnyComponent, FastUI
from starlette.requests import Request

from amiss.data import get_sdps
from amiss.frontend.util import app_page, error_message, sdp_table, sort_links, sort_rows, token_from_request

router = APIRouter()

SDP_SORT_FIELDS = ["status", "stp_a_id", "stp_z_id", "description", "subscription_id"]


@router.get("", response_model=FastUI, response_model_exclude_none=True)
def sdp(request: Request, sort: str | None = None) -> list[AnyComponent]:
    """Display SDP subscriptions reconciled against the DDS topology."""
    result = get_sdps(token_from_request(request))
    if result.error:
        return app_page(error_message(result.error), title="Service Demarcation Points")
    return app_page(
        sort_links("/sdp", SDP_SORT_FIELDS, sort),
        sdp_table(sort_rows(result.rows, sort)),
        title="Service Demarcation Points",
    )
