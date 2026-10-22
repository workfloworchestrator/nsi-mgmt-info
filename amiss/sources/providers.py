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

"""Fetch the uPAs the aggregator peers with, and the reservations each one holds.

The aggregator proxy lists the peered uPAs (``GET /providers``) and queries one uPA directly for every
reservation it holds, whatever the requester (``GET /providers/{nsaId}/reservations``). The DDS proxy
adds each NSA's name, roles and peers (``dds_topology.fetch_dds_nsas``). Fetches return ``None`` on
failure so callers can tell "failed" from "empty".
"""

from urllib.parse import quote

from pydantic import BaseModel, computed_field

from amiss.dds import strip_urn
from amiss.sources.aggregator import get_agg_proxy_list
from amiss.sources.reconcile import by_normalized_id, normalize_id
from amiss.sources.wfo import CircuitRow, StpSub, short_id

PROVIDERS_UNAVAILABLE = "Providers unavailable: the aggregator proxy could not be reached."


class Upa(BaseModel):
    """A peered uPA, as the aggregator proxy lists it."""

    nsa_id: str
    provider_url: str | None = None
    network_ids: list[str] = []


class DdsNsa(BaseModel):
    """The DDS side of an NSA: what the aggregator proxy's provider list leaves out."""

    nsa_id: str
    name: str | None = None
    roles: list[str] = []
    peers_with: list[str] = []


class UpaReservation(BaseModel):
    """One reservation as a uPA reports it, with the raw NSI sub-states."""

    connection_id: str
    global_reservation_id: str | None = None  # NSI makes it optional; the WFO sets it on every circuit
    description: str | None = None
    requester_nsa: str | None = None
    reservation_state: str | None = None
    provision_state: str | None = None
    lifecycle_state: str | None = None
    data_plane_active: bool | None = None
    capacity: int | None = None
    source_stp: str | None = None  # full STP id including ?vlan=
    dest_stp: str | None = None


class ProviderRow(BaseModel):
    """A /providers row. The list fields are joined, because a table cell shows a plain value."""

    nsa_id: str
    name: str
    provider_url: str | None = None
    network_ids: str | None = None
    roles: str | None = None
    peers_with: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def short_nsa_id(self) -> str:
        return strip_urn(self.nsa_id)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def networks(self) -> str | None:
        """The network ids without their URN prefix, for the list."""
        return strip_urn(self.network_ids) if self.network_ids else None


class ProviderReservationRow(UpaReservation):
    """A uPA reservation, plus the WFO subscriptions it links to (``None`` where nothing matches)."""

    subscription_id: str | None = None  # the WFO circuit this reservation is a segment of
    source_stp_subscription_id: str | None = None
    dest_stp_subscription_id: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def short_id(self) -> str | None:
        return short_id(self.subscription_id)


class ProviderList(BaseModel):
    """The /providers result: provider rows, or an ``error`` if they could not be fetched."""

    rows: list[ProviderRow] = []
    error: str | None = None


class ProviderDetail(BaseModel):
    """A provider detail page.

    ``provider`` is ``None`` without an ``error`` when the NSA is not a peered uPA. ``reservations`` is
    ``None`` when the uPA could not be reached, so the details still render without them.
    """

    provider: ProviderRow | None = None
    error: str | None = None
    reservations: list[ProviderReservationRow] | None = None


def _join(values: list[str]) -> str | None:
    return ", ".join(values) or None


def _to_upa(item: dict) -> Upa | None:
    nsa_id = item.get("nsaId")
    return (
        Upa(nsa_id=nsa_id, provider_url=item.get("providerURL"), network_ids=item.get("networkIds") or [])
        if nsa_id
        else None
    )


def _to_reservation(item: dict) -> UpaReservation | None:
    connection_id = item.get("connectionId")
    return (
        UpaReservation(
            connection_id=connection_id,
            global_reservation_id=item.get("globalReservationId"),
            description=item.get("description"),
            requester_nsa=item.get("requesterNSA"),
            reservation_state=item.get("reservationState"),
            provision_state=item.get("provisionState"),
            lifecycle_state=item.get("lifecycleState"),
            data_plane_active=item.get("dataPlaneActive"),
            capacity=item.get("capacity"),
            source_stp=item.get("sourceSTP"),
            dest_stp=item.get("destSTP"),
        )
        if connection_id
        else None
    )


def fetch_providers() -> list[Upa] | None:
    """Fetch the uPAs the aggregator peers with, or ``None`` on failure."""
    items = get_agg_proxy_list("/providers", "providers")
    return None if items is None else [upa for item in items if (upa := _to_upa(item))]


def fetch_provider_reservations(nsa_id: str) -> list[UpaReservation] | None:
    """Fetch every reservation one uPA holds, or ``None`` on failure (including an NSA it does not peer with)."""
    items = get_agg_proxy_list(f"/providers/{quote(nsa_id, safe='')}/reservations", "reservations")
    return None if items is None else [res for item in items if (res := _to_reservation(item))]


def _provider_row(upa: Upa, nsa: DdsNsa | None) -> ProviderRow:
    return ProviderRow(
        nsa_id=upa.nsa_id,
        name=(nsa.name if nsa else None) or upa.nsa_id,
        provider_url=upa.provider_url,
        network_ids=_join(upa.network_ids),
        roles=_join(nsa.roles) if nsa else None,
        peers_with=_join(nsa.peers_with) if nsa else None,
    )


def build_providers(upas: list[Upa] | None, nsas: list[DdsNsa] | None) -> ProviderList:
    """Join the peered uPAs with their DDS NSA documents on the NSA id, sorted by name.

    The aggregator list decides which providers exist. The DDS only adds detail, so without it the rows
    still render, named by their NSA id.
    """
    if upas is None:
        return ProviderList(error=PROVIDERS_UNAVAILABLE)
    nsa_by_id = {nsa.nsa_id: nsa for nsa in nsas or []}
    rows = [_provider_row(upa, nsa_by_id.get(upa.nsa_id)) for upa in upas]
    return ProviderList(rows=sorted(rows, key=lambda row: row.name.lower()))


def link_reservations(
    reservations: list[UpaReservation],
    wfo_circuits: list[CircuitRow] | None,
    stp_subs: list[StpSub] | None,
) -> list[ProviderReservationRow]:
    """Attach the WFO circuit and STP subscriptions each reservation belongs to.

    The aggregator copies the circuit's global reservation id into every child reserve, so it links a uPA
    reservation to its WFO circuit. Reservations without one (NSI makes it optional) or from another
    requester stay unlinked, as do those of a retried circuit, which gets a new id. A missing link source
    leaves its links empty.
    """
    circuit_of = {
        circuit.global_reservation_id: circuit.subscription_id
        for circuit in wfo_circuits or []
        if circuit.global_reservation_id
    }
    stp_by_id = by_normalized_id(stp_subs or [], lambda sub: sub.stp_id)

    def stp_subscription(stp: str | None) -> str | None:
        sub = stp_by_id.get(normalize_id(stp) or "")
        return sub.subscription_id if sub else None

    return [
        ProviderReservationRow(
            **reservation.model_dump(),
            subscription_id=circuit_of.get(reservation.global_reservation_id or ""),
            source_stp_subscription_id=stp_subscription(reservation.source_stp),
            dest_stp_subscription_id=stp_subscription(reservation.dest_stp),
        )
        for reservation in reservations
    ]


def reservation_tab(row: UpaReservation) -> str | None:
    """Classify a reservation by its NSI lifecycle state into the ``active`` or ``terminated`` tab.

    Failed and PassedEndTime reservations are in neither (``None``): they show on the All tab only.
    """
    match row.lifecycle_state:
        case "Created":
            return "active"
        case "Terminating" | "Terminated":
            return "terminated"
        case _:
            return None
