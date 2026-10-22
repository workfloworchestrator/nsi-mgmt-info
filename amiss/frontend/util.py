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
from collections.abc import Collection, Mapping, Sequence
from string import Formatter
from typing import Any

from fastui import AnyComponent
from fastui import components as c
from fastui.components.display import DisplayLookup
from fastui.events import BackEvent, GoToEvent
from pydantic import BaseModel
from starlette.requests import Request

from amiss.settings import settings
from amiss.sources.aggregator import CircuitOnSdp, PathSegment, SpectrumRow
from amiss.sources.providers import ProviderReservationRow, ProviderRow
from amiss.sources.reconcile import NamedRow, ReconcileStatus, SdpRow, StpRow
from amiss.sources.wfo import CircuitRow, ValidationFailureRow

# do not know why, but otherwise FastUI will complain
c.Link.model_rebuild()


def root_url(path: str) -> str:
    """Prefix an internal SPA path with ``ROOT_PATH``.

    FastUI's ``api_path_strip`` expects the browser path to keep the deploy prefix (e.g. ``/amiss``);
    it strips it only for the API call. So every internal navigation URL, ``active`` matcher and form
    ``submit_url`` must carry the prefix, or navigation drops it from the browser URL. No-op when
    ``ROOT_PATH`` is empty (local/dev).
    """
    return f"{settings.ROOT_PATH}{path}"


_NAV_LINKS = (
    ("Circuits", "/circuits"),
    ("Topology", "/topology"),
    ("Switch", "/switching-service"),
    ("STP", "/stp"),
    ("SDP", "/sdp"),
    ("Spectrum", "/spectrum"),
    ("Providers", "/providers"),
)


def app_page(*components: AnyComponent, title: str | None = None) -> list[AnyComponent]:
    return [
        c.PageTitle(text=f"AMISS — {title}" if title else "AMISS"),
        c.Navbar(
            title=settings.SITE_TITLE,
            title_event=GoToEvent(url=root_url("/")),
            start_links=[
                c.Link(
                    components=[c.Text(text=label)],
                    on_click=GoToEvent(url=root_url(path)),
                    active=f"startswith:{root_url(path)}",
                )
                for label, path in _NAV_LINKS
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
                src=root_url("/static/ana-logo-scaled-ab2.png"),
                alt="ANA logo",
                width=400,
                height=232,
                loading="lazy",
                referrer_policy="no-referrer",
            )
        ],
        class_name="+ d-flex justify-content-center mt-4",
    )


_ACCESS_TOKEN_HEADERS = ("X-Auth-Request-Access-Token", "X-Forwarded-Access-Token")


def token_from_request(request: Request) -> str | None:
    """Extract the end-user's OIDC access token to forward to the WFO.

    The portal's oauth2-proxy injects ``X-Auth-Request-Access-Token`` (this stack's ``X-Auth-Request-*``
    convention); ``X-Forwarded-Access-Token`` (oauth2-proxy reverse-proxy mode) and a raw
    ``Authorization: Bearer`` header are accepted as fallbacks (e.g. local testing with a token).
    """
    header_token = next((token for h in _ACCESS_TOKEN_HEADERS if (token := request.headers.get(h))), None)
    if header_token:
        return header_token
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


# (key, label, path) per tab. The path doubles as the sort form's submit_url, so sorting stays in-tab.
type Tabs = tuple[tuple[str, str, str], ...]


def tab_links(tabs: Tabs) -> AnyComponent:
    """Build the tab bar of a tabbed list page.

    The first tab's path is the page's base path, which would prefix-match every other tab, so it is
    matched exactly; FastUI marks the active tab by matching these patterns against the current URL.
    """
    base = tabs[0][2]
    return c.LinkList(
        links=[
            c.Link(
                components=[c.Text(text=label)],
                on_click=GoToEvent(url=root_url(path)),
                active=(root_url(path) if path == base else f"startswith:{root_url(path)}"),
            )
            for _key, label, path in tabs
        ],
        mode="tabs",
        class_name="+ mb-4",
    )


def tab_path(tabs: Tabs, tab: str) -> str:
    return next(path for key, _label, path in tabs if key == tab)


# The status each tab of /stp and /sdp holds, keyed by tab key; "all" (no status) is the default tab,
# because the whole inventory is the usual reason to open these pages.
_RECONCILE_TABS = (
    ("all", "All", "", None),
    ("in_both", "Backed by DDS", "/backed", ReconcileStatus.IN_BOTH),
    ("missing_in_dds", "Not in DDS", "/missing", ReconcileStatus.MISSING_IN_DDS),
    ("dds_only", "DDS only", "/dds-only", ReconcileStatus.DDS_ONLY),
)
_TAB_STATUS = {key: status for key, _label, _suffix, status in _RECONCILE_TABS}


def reconcile_tabs(base: str) -> Tabs:
    """Build the status tabs of a reconciliation page, rooted at ``base`` (``/stp`` or ``/sdp``)."""
    return tuple((key, label, f"{base}{suffix}") for key, label, suffix, _status in _RECONCILE_TABS)


def in_tab(row: StpRow | SdpRow | NamedRow, tab: str) -> bool:
    """Whether a reconciled row belongs in the given status tab (the 'all' tab holds everything)."""
    status = _TAB_STATUS[tab]
    return status is None or row.status is status


def sort_form(form_model: type[BaseModel], submit_url: str, current: str | None) -> AnyComponent:
    """Build an inline 'Sort by' dropdown that re-sorts the table by navigating to ?sort=<field>.

    ``form_model`` is a one-field pydantic model whose ``sort`` enum lists the table's sortable
    columns; changing the select navigates to ``submit_url?sort=<field>`` (server-side sort).
    """
    return c.ModelForm(
        model=form_model,
        submit_url=submit_url,
        method="GOTO",
        submit_on_change=True,
        display_mode="inline",
        initial={"sort": current} if current else {},
    )


# Every list table leads with the 8-char subscription id, linking to that row's detail page. Rows
# without a subscription (an STP/SDP the DDS knows but the WFO does not) render it as an inert '—':
# FastUI drops a go-to event whose url interpolates a missing field.
def _id_column(detail_path: str, title: str = "ID") -> DisplayLookup:
    return _linked("short_id", detail_path, title)


def _linked(field: str, path: str, title: str | None = None) -> DisplayLookup:
    """Show ``field``, linking to ``path``; the same missing-field rule leaves the cell inert."""
    return DisplayLookup(field=field, title=title, on_click=GoToEvent(url=root_url(path)))


provider_column = _linked("provider_name", "/providers/{provider_nsa}/", "Provider")


def circuit_table(circuits: list[CircuitRow]) -> c.Table:
    return c.Table(
        data_model=CircuitRow,
        data=circuits,
        columns=[
            _id_column("/circuits/{subscription_id}/"),
            DisplayLookup(field="description"),
            DisplayLookup(field="start_time"),
            _linked("source", "/stp/{source_stp_subscription_id}/", "Source"),
            _linked("dest", "/stp/{dest_stp_subscription_id}/", "Destination"),
            DisplayLookup(field="bandwidth", title="Bandwidth"),
            DisplayLookup(field="state"),
            DisplayLookup(field="created_by_name", title="Created By"),
        ],
        class_name="+ small",
    )


def named_table(rows: list[NamedRow], id_title: str, extra_columns: Sequence[DisplayLookup] = ()) -> c.Table:
    return c.Table(
        data_model=NamedRow,
        data=rows,
        columns=[
            DisplayLookup(field="short_id", title="ID"),
            DisplayLookup(field="short_object_id", title=id_title),
            DisplayLookup(field="description", title="Name"),
            *extra_columns,
            DisplayLookup(field="wfo_status", title="Lifecycle"),
            DisplayLookup(field="status"),
        ],
        class_name="+ small",
    )


def stp_table(stps: list[StpRow]) -> c.Table:
    return c.Table(
        data_model=StpRow,
        data=stps,
        columns=[
            _id_column("/stp/{subscription_id}/"),
            DisplayLookup(field="description"),
            DisplayLookup(field="network", title="Network"),
            DisplayLookup(field="port", title="Port"),
            DisplayLookup(field="vlan_range", title="VLANs"),
            DisplayLookup(field="capacity", title="Capacity"),
            DisplayLookup(field="status"),
        ],
        class_name="+ small",
    )


def sdp_table(sdps: list[SdpRow]) -> c.Table:
    return c.Table(
        data_model=SdpRow,
        data=sdps,
        columns=[
            _id_column("/sdp/{subscription_id}/"),
            DisplayLookup(field="description"),
            _linked("stp_a_name", "/stp/{stp_a_subscription_id}/", "STP A"),
            _linked("stp_z_name", "/stp/{stp_z_subscription_id}/", "STP Z"),
            DisplayLookup(field="vlan_range", title="VLANs"),
            DisplayLookup(field="capacity", title="Capacity"),
            DisplayLookup(field="status"),
        ],
        class_name="+ small",
    )


def validation_failure_table(rows: list[ValidationFailureRow]) -> c.Table:
    return c.Table(
        data_model=ValidationFailureRow,
        data=rows,
        columns=[
            DisplayLookup(field="short_id", title="ID"),
            DisplayLookup(field="workflow_name", title="Check"),
            DisplayLookup(field="description", title="Subscription"),
            DisplayLookup(field="last_status", title="Status"),
            DisplayLookup(field="started_at", title="Last seen"),
            DisplayLookup(field="occurrences", title="Times"),
            DisplayLookup(field="reason", title="Reason"),
        ],
        # Full reasons carry URNs with no spaces; validation-failures lets the last (Reason) cell break them.
        class_name="+ small validation-failures",
    )


def spectrum_sdp_table(rows: list[SpectrumRow]) -> c.Table:
    return c.Table(
        data_model=SpectrumRow,
        data=rows,
        columns=[
            _linked("sdp_name", "/sdp/{subscription_id}/", "SDP"),
            _linked("stp_a", "/stp/{stp_a_subscription_id}/", "STP A"),
            _linked("stp_z", "/stp/{stp_z_subscription_id}/", "STP Z"),
            DisplayLookup(field="circuit_count", title="Circuits"),
            DisplayLookup(field="sdp_capacity", title="Capacity"),
            DisplayLookup(field="total_capacity", title="Reserved"),
            DisplayLookup(field="utilisation", title="Used %"),
        ],
        class_name="+ small",
    )


def spectrum_circuit_table(circuits: list[CircuitOnSdp]) -> c.Table:
    return c.Table(
        data_model=CircuitOnSdp,
        data=circuits,
        columns=[
            _id_column("/circuits/{subscription_id}/"),
            DisplayLookup(field="description"),
            DisplayLookup(field="vlan", title="VLAN"),
            DisplayLookup(field="bandwidth", title="Bandwidth"),
            DisplayLookup(field="status"),
            DisplayLookup(field="connection_id"),
        ],
        class_name="+ small",
    )


def segment_table(segments: list[PathSegment]) -> c.Table:
    return c.Table(
        data_model=PathSegment,
        data=segments,
        columns=[
            DisplayLookup(field="order"),
            _linked("short_provider_nsa", "/providers/{provider_nsa}/", "Provider NSA"),
            _linked("source", "/stp/{source_stp_subscription_id}/", "Source STP"),
            _linked("dest", "/stp/{dest_stp_subscription_id}/", "Dest STP"),
            DisplayLookup(field="capacity"),
            DisplayLookup(field="status"),
        ],
        class_name="+ small",
    )


def provider_table(rows: list[ProviderRow]) -> c.Table:
    return c.Table(
        data_model=ProviderRow,
        data=rows,
        columns=[
            _linked("name", "/providers/{nsa_id}/"),
            DisplayLookup(field="short_nsa_id", title="NSA ID"),
            DisplayLookup(field="networks", title="Networks"),
            DisplayLookup(field="provider_url", title="Provider URL"),
        ],
        class_name="+ small",
    )


def provider_reservation_table(rows: list[ProviderReservationRow]) -> c.Table:
    return c.Table(
        data_model=ProviderReservationRow,
        data=rows,
        columns=[
            _id_column("/circuits/{subscription_id}/", title="Circuit"),
            DisplayLookup(field="connection_id"),
            _linked("source", "/stp/{source_stp_subscription_id}/", "Source STP"),
            _linked("dest", "/stp/{dest_stp_subscription_id}/", "Dest STP"),
            DisplayLookup(field="capacity"),
            DisplayLookup(field="reservation_state", title="Reservation"),
            DisplayLookup(field="provision_state", title="Provision"),
            DisplayLookup(field="lifecycle_state", title="Lifecycle"),
            DisplayLookup(field="data_plane_active", title="Data plane"),
        ],
        class_name="+ small",
    )


def button_row(buttons: list[c.Button]) -> c.Div:
    # gap: between elements, py: padding y-axis
    return c.Div(components=buttons, class_name="d-flex flex-row gap-1 py-3")


def _orchestrator_button(subscription_id: str | None) -> list[c.Button]:
    """Open the subscription in the orchestrator UI, in a new tab; none without a subscription or UI URL."""
    if not (subscription_id and settings.NSI_AMISS_WFO_UI_URL):
        return []
    url = f"{str(settings.NSI_AMISS_WFO_UI_URL).rstrip('/')}/subscriptions/{subscription_id}"
    return [
        c.Button(text="Open in orchestrator", on_click=GoToEvent(url=url, target="_blank"), named_style="secondary")
    ]


def detail_buttons(list_path: str, list_title: str, subscription_id: str | None = None) -> c.Div:
    """Build the button row every detail page opens with.

    Back follows the browser history, so it returns to whichever page linked here. It goes nowhere useful
    on a page opened from a bookmark, hence the second button to the list.
    """
    return button_row(
        [
            c.Button(text="Back", on_click=BackEvent(), class_name="+ ms-2"),
            c.Button(text=f"All {list_title}", on_click=GoToEvent(url=root_url(list_path)), named_style="secondary"),
            *_orchestrator_button(subscription_id),
        ]
    )


def _placeholders(path: str) -> set[str]:
    """Return the field names a link path interpolates, e.g. ``{"stp_a_subscription_id"}``."""
    return {name for _text, name, _spec, _conversion in Formatter().parse(path) if name}


def detail_fields(
    model: type[BaseModel], exclude: Collection[str] = (), links: Mapping[str, str] | None = None
) -> list[DisplayLookup]:
    """Every field of a row model, for a detail page.

    Computed fields are not in ``model_fields``, so the list-only ones a table derives (``short_id``,
    ``network``/``port``) drop out for free; ``exclude`` is for stored fields the list shows instead.
    ``links`` maps a field to the path it links to; the ids a path interpolates are link targets only, so
    they are left out too.
    """
    links = links or {}
    targets = set().union(*map(_placeholders, links.values()))
    return [
        _linked(name, links[name]) if name in links else DisplayLookup(field=name)
        for name, field in model.model_fields.items()
        if name not in exclude and name not in targets and not field.exclude
    ]
