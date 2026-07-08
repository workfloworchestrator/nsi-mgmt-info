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
from typing import Any

from fastui import AnyComponent
from fastui import components as c
from fastui.components.display import DisplayLookup
from fastui.events import GoToEvent
from starlette.requests import Request

from amiss.model import SDP, Segment
from amiss.settings import settings
from amiss.sources.reconcile import SdpRow, StpRow
from amiss.sources.wfo import CircuitRow

# do not know why, but otherwise FastUI will complain
c.Link.model_rebuild()


def app_page(*components: AnyComponent, title: str | None = None) -> list[AnyComponent]:
    return [
        c.PageTitle(text=f"AMISS — {title}" if title else "AMISS"),
        c.Navbar(
            title=settings.SITE_TITLE,
            title_event=GoToEvent(url="/"),
            start_links=[
                c.Link(
                    components=[c.Text(text="Circuits")],
                    on_click=GoToEvent(url="/circuits"),
                    active="startswith:/circuits",
                ),
                c.Link(
                    components=[c.Text(text="STP")],
                    on_click=GoToEvent(url="/stp"),
                    active="startswith:/stp",
                ),
                c.Link(
                    components=[c.Text(text="SDP")],
                    on_click=GoToEvent(url="/sdp"),
                    active="startswith:/sdp",
                ),
                c.Link(
                    components=[c.Text(text="Spectrum")],
                    on_click=GoToEvent(url="/spectrum/active"),
                    active="startswith:/spectrum",
                ),
            ],
        ),
        c.Page(
            components=[
                *((c.Heading(text=title),) if title else ()),
                *components,
                amiss_logo(),
            ],
        ),
        c.Footer(
            extra_text="AMISS",
            links=[
                c.Link(
                    components=[c.Text(text="Github")],
                    on_click=GoToEvent(url="https://github.com/workfloworchestrator/nsi-mgmt-info/"),
                ),
            ],
        ),
    ]


def amiss_logo() -> AnyComponent:
    return c.Div(
        components=[
            c.Image(
                src=f"{settings.ROOT_PATH}/static/ANA-logo-scaled-ab3.png",
                alt="ANA footer Logo",
                width=800,
                height=58,
                loading="lazy",
                referrer_policy="no-referrer",
            )
        ],
        class_name="+ d-flex justify-content-center",
    )


def token_from_request(request: Request) -> str | None:
    """Extract the end-user's OIDC access token to forward to the WFO.

    The portal's oauth2-proxy injects ``X-Forwarded-Access-Token``; a raw ``Authorization: Bearer``
    header is accepted as a fallback (e.g. local testing with a token).
    """
    forwarded = request.headers.get("X-Forwarded-Access-Token")
    if forwarded:
        return forwarded
    authorization = request.headers.get("Authorization", "")
    return authorization[7:] if authorization.lower().startswith("bearer ") else None


def error_message(text: str) -> AnyComponent:
    """Build a warning banner for when a source is unavailable (so the table never shows a false diff)."""
    return c.Div(components=[c.Text(text=text)], class_name="+ alert alert-warning")


def _sort_key(row: object, field: str) -> tuple[int, Any]:
    """Sort key that orders missing values last and compares strings case-insensitively."""
    value = getattr(row, field, None)
    if value is None:
        return (1, "")
    if isinstance(value, str):
        return (0, value.lower())
    return (0, value)


def sort_rows[T](rows: list[T], sort: str | None) -> list[T]:
    """Sort rows by the ``sort`` attribute (missing values last); unsorted when ``sort`` is None."""
    return sorted(rows, key=lambda row: _sort_key(row, sort)) if sort else rows


def sort_links(base_url: str, fields: list[str], current: str | None) -> AnyComponent:
    """Build a 'Sort by' row of links; the active field is emphasised."""
    return c.Div(
        components=[
            c.Text(text="Sort by: "),
            *[
                c.Link(
                    components=[c.Text(text=field)],
                    on_click=GoToEvent(url=f"{base_url}?sort={field}"),
                    class_name="+ me-3 fw-bold" if field == current else "+ me-3",
                )
                for field in fields
            ],
        ],
        class_name="+ mb-3 small",
    )


def circuit_table(circuits: list[CircuitRow]) -> c.Table:
    return c.Table(
        data_model=CircuitRow,
        data=circuits,
        columns=[
            DisplayLookup(field="subscription_id", on_click=GoToEvent(url="/circuits/{subscription_id}/")),
            DisplayLookup(field="description"),
            DisplayLookup(field="start_time"),
            DisplayLookup(field="end_time"),
            DisplayLookup(field="source_stp"),
            DisplayLookup(field="source_vlan"),
            DisplayLookup(field="dest_stp"),
            DisplayLookup(field="dest_vlan"),
            DisplayLookup(field="bandwidth"),
            DisplayLookup(field="state"),
            DisplayLookup(field="created_by"),
        ],
        class_name="+ small",
    )


def stp_table(stps: list[StpRow]) -> c.Table:
    return c.Table(
        data_model=StpRow,
        data=stps,
        columns=[
            DisplayLookup(field="stp_id"),
            DisplayLookup(field="vlan_range"),
            DisplayLookup(field="description"),
            DisplayLookup(field="subscription_id"),
            DisplayLookup(field="status"),
        ],
        class_name="+ small",
    )


def sdp_table(sdps: list[SdpRow]) -> c.Table:
    return c.Table(
        data_model=SdpRow,
        data=sdps,
        columns=[
            DisplayLookup(field="stp_a_id"),
            DisplayLookup(field="stp_z_id"),
            DisplayLookup(field="vlan_range"),
            DisplayLookup(field="description"),
            DisplayLookup(field="subscription_id"),
            DisplayLookup(field="status"),
        ],
        class_name="+ small",
    )


def spectrum_table(sdps: list[SDP]) -> c.Table:
    return c.Table(
        data_model=SDP,
        data=sdps,
        columns=[
            DisplayLookup(field="id", on_click=GoToEvent(url="/spectrum/{id}/")),
            DisplayLookup(field="description"),
            DisplayLookup(field="vlanRange"),
        ],
        class_name="+ small",
    )


def segment_table(segments: list[Segment]) -> c.Table:
    return c.Table(
        data_model=Segment,
        data=segments,
        columns=[
            DisplayLookup(field="id"),
            DisplayLookup(field="circuit_id"),
            DisplayLookup(field="order"),
            DisplayLookup(field="sourceStp"),
            DisplayLookup(field="destStp"),
            DisplayLookup(field="capacity"),
        ],
        class_name="+ small",
    )


def button_row(buttons: list[c.Button]) -> c.Div:
    # gap: between elements, py: padding y-axis
    return c.Div(components=buttons, class_name="d-flex flex-row gap-1 py-3")
