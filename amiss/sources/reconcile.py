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

"""Reconcile the WFO STP/SDP subscriptions against the DDS topology.

Each row is tagged so the UI can show which subscriptions are backed by the DDS, which topology has
no subscription yet, and which subscriptions the DDS no longer knows about. If either source failed
to fetch (``None``, distinct from an empty list), the reconciliation returns an ``error`` and no rows
— a diff computed from a failed fetch would falsely flag everything.
"""

from collections.abc import Callable, Iterable
from enum import Enum

from pydantic import BaseModel

from amiss.sources.wfo import SdpSub, StpSub


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
    """The DDS side of an SDP: the two member STP ids plus display fields."""

    stp_a_id: str
    stp_z_id: str
    vlan_range: str | None = None
    description: str | None = None


class StpRow(BaseModel):
    """A reconciled STP row for /stp."""

    stp_id: str | None = None
    vlan_range: str | None = None
    description: str | None = None
    subscription_id: str | None = None
    status: ReconcileStatus


class SdpRow(BaseModel):
    """A reconciled SDP row for /sdp."""

    stp_a_id: str | None = None
    stp_z_id: str | None = None
    vlan_range: str | None = None
    description: str | None = None
    subscription_id: str | None = None
    status: ReconcileStatus


class StpReconciliation(BaseModel):
    rows: list[StpRow] = []
    error: str | None = None


class SdpReconciliation(BaseModel):
    rows: list[SdpRow] = []
    error: str | None = None


def normalize_stp_id(raw: str | None) -> str | None:
    """Normalise an STP id for matching: drop the URN prefix and any ``?…`` query suffix.

    Case is preserved: the DDS and WFO both derive ids from the same NSI topology, so casing already
    matches, and lowercasing could merge genuinely distinct ports.
    """
    if not raw:
        return None
    normalized = raw.strip().removeprefix("urn:ogf:network:").split("?", 1)[0]
    return normalized or None


def _by_normalized_id[T](items: Iterable[T], id_of: Callable[[T], str | None]) -> dict[str, T]:
    """Index items by their normalised STP id, dropping those without one (last wins on collision)."""
    return {nid: item for item in items if (nid := normalize_stp_id(id_of(item)))}


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
        stp_id=(dds.stp_id if dds else wfo.stp_id if wfo else nid),
        vlan_range=(dds.vlan_range if dds else None) or (wfo.label_group if wfo else None),
        description=(dds.description if dds else None) or (wfo.stp_name if wfo else None),
        subscription_id=wfo.subscription_id if wfo else None,
        status=_status(wfo is not None, dds is not None),
    )


def reconcile_stps(wfo: list[StpSub] | None, dds: list[DdsStp] | None) -> StpReconciliation:
    """Reconcile WFO STP subscriptions against DDS STPs, matched on the normalised STP id."""
    if wfo is None and dds is None:
        return StpReconciliation(error="STP reconciliation unavailable: a source could not be reached")
    if wfo is None:
        wfo = []
    if dds is None:
        dds = []
    wfo_by_id = _by_normalized_id(wfo, lambda s: s.stp_id)
    dds_by_id = _by_normalized_id(dds, lambda d: d.stp_id)
    ids = sorted(set(wfo_by_id) | set(dds_by_id))
    return StpReconciliation(rows=[_stp_row(nid, wfo_by_id, dds_by_id) for nid in ids])


def sdp_pair(raw_ids: Iterable[str | None]) -> frozenset[str] | None:
    """Build the unordered match key of an SDP: its two distinct normalised STP ids, or ``None``."""
    ids = {nid for raw in raw_ids if (nid := normalize_stp_id(raw))}
    return frozenset(ids) if len(ids) == 2 else None


def _sdp_row(
    pair: frozenset[str], wfo_by_pair: dict[frozenset[str], SdpSub], dds_by_pair: dict[frozenset[str], DdsSdp]
) -> SdpRow:
    wfo = wfo_by_pair.get(pair)
    dds = dds_by_pair.get(pair)
    stp_a, stp_z = (dds.stp_a_id, dds.stp_z_id) if dds else tuple(sorted(pair))
    return SdpRow(
        stp_a_id=stp_a,
        stp_z_id=stp_z,
        vlan_range=(dds.vlan_range if dds else None),
        description=(dds.description if dds else None) or (wfo.sdp_name if wfo else None),
        subscription_id=wfo.subscription_id if wfo else None,
        status=_status(wfo is not None, dds is not None),
    )


def reconcile_sdps(wfo: list[SdpSub] | None, dds: list[DdsSdp] | None) -> SdpReconciliation:
    """Reconcile WFO SDP subscriptions against DDS SDPs, matched on the unordered pair of STP ids."""
    if wfo is None and dds is None:
        return SdpReconciliation(error="SDP reconciliation unavailable: a source could not be reached")
    if wfo is None:
        wfo = []
    if dds is None:
        dds = []
    wfo_by_pair = {pair: s for s in wfo if (pair := sdp_pair(member.stp_id for member in s.stps))}
    dds_by_pair = {pair: d for d in dds if (pair := sdp_pair((d.stp_a_id, d.stp_z_id)))}
    pairs = sorted(set(wfo_by_pair) | set(dds_by_pair), key=lambda p: tuple(sorted(p)))
    return SdpReconciliation(rows=[_sdp_row(pair, wfo_by_pair, dds_by_pair) for pair in pairs])
