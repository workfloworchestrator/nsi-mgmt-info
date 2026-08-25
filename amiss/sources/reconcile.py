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

"""Reconcile the WFO Topology/SwitchingService/STP/SDP subscriptions against the DDS topology.

Each row is tagged so the UI can show which subscriptions are backed by the DDS, which topology has
no subscription yet, and which subscriptions the DDS no longer knows about. If either source failed
to fetch (``None``, distinct from an empty list), the reconciliation returns an ``error`` and no rows
— a diff computed from a failed fetch would falsely flag everything.
"""

from collections.abc import Callable, Iterable
from enum import Enum

from pydantic import BaseModel, computed_field

from amiss.sources.wfo import NamedSub, SdpMember, SdpSub, StpSub, short_id


class ReconcileStatus(str, Enum):
    """Where an STP/SDP is present."""

    IN_BOTH = "backed by DDS"
    DDS_ONLY = "DDS only (no subscription)"
    MISSING_IN_DDS = "subscription not in DDS"


class DdsStp(BaseModel):
    """The DDS side of an STP (from the DDS proxy topology)."""

    stp_id: str
    vlan_range: str | None = None
    description: str | None = None


class DdsSdp(BaseModel):
    """The DDS side of an SDP: the proxy reports nothing but the two member STP ids."""

    stp_a_id: str
    stp_z_id: str


class StpRow(BaseModel):
    """A reconciled STP row for /stp."""

    subscription_id: str | None = None  # absent on a DDS_ONLY row: there is no subscription yet
    stp_id: str | None = None
    description: str | None = None
    vlan_range: str | None = None
    capacity: int | None = None
    wfo_status: str | None = None  # the subscription's own lifecycle, distinct from `status` below
    status: ReconcileStatus

    @computed_field  # type: ignore[prop-decorator]
    @property
    def short_id(self) -> str | None:
        return short_id(self.subscription_id)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def network(self) -> str | None:
        """The topology part of the STP id, split off because it repeats identically down the table."""
        # ponytail: split on the last colon; parse the URN properly if a local id ever contains one
        return (self.stp_id.rpartition(":")[0] or None) if self.stp_id else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def port(self) -> str | None:
        """The STP id without its topology prefix."""
        return self.stp_id.rpartition(":")[2] if self.stp_id else None


class SdpRow(BaseModel):
    """A reconciled SDP row for /sdp."""

    subscription_id: str | None = None
    stp_a_id: str | None = None
    stp_z_id: str | None = None
    # what the table shows for each end: the port's name, falling back to its id where the WFO has none
    stp_a_name: str | None = None
    stp_z_name: str | None = None
    description: str | None = None
    vlan_range: str | None = None
    capacity: int | None = None
    wfo_status: str | None = None
    status: ReconcileStatus

    @computed_field  # type: ignore[prop-decorator]
    @property
    def short_id(self) -> str | None:
        return short_id(self.subscription_id)


class DdsNamed(BaseModel):
    """The DDS side of a flat id-plus-name object: a Topology or a SwitchingService."""

    object_id: str
    name: str | None = None


class NamedRow(BaseModel):
    """A reconciled Topology or SwitchingService row."""

    subscription_id: str | None = None  # absent on a DDS_ONLY row: not subscribed yet
    object_id: str | None = None
    description: str | None = None
    wfo_status: str | None = None
    status: ReconcileStatus

    @computed_field  # type: ignore[prop-decorator]
    @property
    def short_id(self) -> str | None:
        return short_id(self.subscription_id)


class NamedReconciliation(BaseModel):
    rows: list[NamedRow] = []
    error: str | None = None


class StpReconciliation(BaseModel):
    rows: list[StpRow] = []
    error: str | None = None


class SdpReconciliation(BaseModel):
    rows: list[SdpRow] = []
    error: str | None = None


def normalize_id(raw: str | None) -> str | None:
    """Normalise an NSI URN for matching: drop the URN prefix and any ``?…`` query suffix.

    Case is preserved: the DDS and WFO both derive ids from the same NSI topology, so casing already
    matches, and lowercasing could merge genuinely distinct ports.
    """
    if not raw:
        return None
    normalized = raw.strip().removeprefix("urn:ogf:network:").split("?", 1)[0]
    return normalized or None


def _by_normalized_id[T](items: Iterable[T], id_of: Callable[[T], str | None]) -> dict[str, T]:
    """Index items by their normalised STP id, dropping those without one (last wins on collision)."""
    return {nid: item for item in items if (nid := normalize_id(id_of(item)))}


def _status(in_wfo: bool, in_dds: bool) -> ReconcileStatus:
    match (in_wfo, in_dds):
        case (True, True):
            return ReconcileStatus.IN_BOTH
        case (False, True):
            return ReconcileStatus.DDS_ONLY
        case _:
            return ReconcileStatus.MISSING_IN_DDS


def _stp_row(nid: str, wfo_by_id: dict[str, StpSub], dds_by_id: dict[str, DdsStp]) -> StpRow:
    wfo = wfo_by_id.get(nid)
    dds = dds_by_id.get(nid)
    return StpRow(
        subscription_id=wfo.subscription_id if wfo else None,
        stp_id=(dds.stp_id if dds else wfo.stp_id if wfo else nid),
        description=(dds.description if dds else None) or (wfo.stp_name if wfo else None),
        vlan_range=(dds.vlan_range if dds else None) or (wfo.label_group if wfo else None),
        capacity=wfo.capacity if wfo else None,
        wfo_status=wfo.status if wfo else None,
        status=_status(wfo is not None, dds is not None),
    )


def reconcile_stps(wfo: list[StpSub] | None, dds: list[DdsStp] | None) -> StpReconciliation:
    """Reconcile WFO STP subscriptions against DDS STPs, matched on the normalised STP id."""
    if wfo is None or dds is None:
        return StpReconciliation(error="STP reconciliation unavailable: a source could not be reached")
    wfo_by_id = _by_normalized_id(wfo, lambda s: s.stp_id)
    dds_by_id = _by_normalized_id(dds, lambda d: d.stp_id)
    ids = sorted(set(wfo_by_id) | set(dds_by_id))
    return StpReconciliation(rows=[_stp_row(nid, wfo_by_id, dds_by_id) for nid in ids])


def _named_row(nid: str, wfo_by_id: dict[str, NamedSub], dds_by_id: dict[str, DdsNamed]) -> NamedRow:
    wfo = wfo_by_id.get(nid)
    dds = dds_by_id.get(nid)
    return NamedRow(
        subscription_id=wfo.subscription_id if wfo else None,
        object_id=(dds.object_id if dds else wfo.object_id if wfo else nid),
        # The WFO name wins: renaming via modify is deliberate, not drift.
        description=(wfo.name if wfo else None) or (dds.name if dds else None),
        wfo_status=wfo.status if wfo else None,
        status=_status(wfo is not None, dds is not None),
    )


def reconcile_named(wfo: list[NamedSub] | None, dds: list[DdsNamed] | None, what: str) -> NamedReconciliation:
    """Reconcile WFO Topology/SwitchingService subscriptions against the DDS, matched on normalised id."""
    if wfo is None or dds is None:
        return NamedReconciliation(error=f"{what} reconciliation unavailable: a source could not be reached")
    wfo_by_id = _by_normalized_id(wfo, lambda s: s.object_id)
    dds_by_id = _by_normalized_id(dds, lambda d: d.object_id)
    ids = sorted(set(wfo_by_id) | set(dds_by_id))
    return NamedReconciliation(rows=[_named_row(nid, wfo_by_id, dds_by_id) for nid in ids])


def sdp_pair(raw_ids: Iterable[str | None]) -> frozenset[str] | None:
    """Build the unordered match key of an SDP: its two distinct normalised STP ids, or ``None``."""
    ids = {nid for raw in raw_ids if (nid := normalize_id(raw))}
    return frozenset(ids) if len(ids) == 2 else None


def sdp_capacity(sdp: SdpSub) -> int | None:
    """Return the SDP's own capacity: the lower of its two ends, which is what the link can carry."""
    capacities = [member.capacity for member in sdp.stps if member.capacity is not None]
    return min(capacities) if capacities else None


def sdp_ends(wfo: SdpSub | None, stp_a: str, stp_z: str) -> tuple[SdpMember | None, SdpMember | None]:
    """Return the SDP's two members in the given A/Z order.

    ``wfo.stps`` is in the order the orchestrator happens to return, which is unrelated to the A/Z
    order a row displays, so the members are looked up by id — never by list position, or a row can
    show its two ends' values swapped against the columns beside them.
    """
    by_id = _by_normalized_id(wfo.stps if wfo else [], lambda member: member.stp_id)
    return by_id.get(normalize_id(stp_a) or ""), by_id.get(normalize_id(stp_z) or "")


def end_label(end: SdpMember | None, stp_id: str) -> str:
    """Label one end of an SDP: its port name, falling back to the id where the WFO has no name."""
    return (end.stp_name if end else None) or stp_id


def _shared(a: str | None, z: str | None) -> str | None:
    """Render a value the SDP's two ends should share: one value when they agree, both when they do not.

    The ends of one inter-domain link ought to match; a disagreement is itself a defect this page
    exists to surface, so it is shown rather than reduced away.
    """
    return " | ".join(dict.fromkeys(value for value in (a, z) if value)) or None


def _sdp_row(
    pair: frozenset[str], wfo_by_pair: dict[frozenset[str], SdpSub], dds_by_pair: dict[frozenset[str], DdsSdp]
) -> SdpRow:
    wfo = wfo_by_pair.get(pair)
    dds = dds_by_pair.get(pair)
    stp_a, stp_z = (dds.stp_a_id, dds.stp_z_id) if dds else tuple(sorted(pair))
    end_a, end_z = sdp_ends(wfo, stp_a, stp_z)
    return SdpRow(
        subscription_id=wfo.subscription_id if wfo else None,
        stp_a_id=stp_a,
        stp_z_id=stp_z,
        stp_a_name=end_label(end_a, stp_a),
        stp_z_name=end_label(end_z, stp_z),
        description=wfo.sdp_name if wfo else None,
        vlan_range=_shared(end_a.label_group if end_a else None, end_z.label_group if end_z else None),
        # Unlike the VLAN range, capacity stays a number so the column sorts and /spectrum can divide by it.
        capacity=sdp_capacity(wfo) if wfo else None,
        wfo_status=wfo.status if wfo else None,
        status=_status(wfo is not None, dds is not None),
    )


def reconcile_sdps(wfo: list[SdpSub] | None, dds: list[DdsSdp] | None) -> SdpReconciliation:
    """Reconcile WFO SDP subscriptions against DDS SDPs, matched on the unordered pair of STP ids."""
    if wfo is None or dds is None:
        return SdpReconciliation(error="SDP reconciliation unavailable: a source could not be reached")
    wfo_by_pair = {pair: s for s in wfo if (pair := sdp_pair(member.stp_id for member in s.stps))}
    dds_by_pair = {pair: d for d in dds if (pair := sdp_pair((d.stp_a_id, d.stp_z_id)))}
    pairs = sorted(set(wfo_by_pair) | set(dds_by_pair), key=lambda p: tuple(sorted(p)))
    return SdpReconciliation(rows=[_sdp_row(pair, wfo_by_pair, dds_by_pair) for pair in pairs])
