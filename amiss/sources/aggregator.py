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

"""Fetch circuit paths from the aggregator proxy and group them by the SDP they cross.

The WFO knows a circuit's endpoints but not its multi-domain path; the aggregator proxy does. We fetch
every reservation with full segment detail (``GET /reservations?detail=full``, over the same proxy
identity — mTLS or edge headers — as the DDS proxy) and, for each SDP (from the WFO SDP
subscriptions), list the circuits crossing it. The fetch returns ``None`` on failure so callers can
tell "failed" from "empty".
"""

import json
from collections.abc import Iterator

import structlog
from pydantic import BaseModel, HttpUrl

from amiss.nsi import nsi_util_get_json
from amiss.settings import settings
from amiss.sources.reconcile import normalize_stp_id, sdp_pair
from amiss.sources.wfo import CircuitRow, SdpSub, circuit_state_bucket

logger = structlog.get_logger(__name__)


class PathSegment(BaseModel):
    """One per-domain leg of a circuit's path (aggregator-proxy segment)."""

    order: int | None = None
    source_stp: str | None = None
    dest_stp: str | None = None
    capacity: int | None = None
    provider_nsa: str | None = None
    status: str | None = None


class AggCircuit(BaseModel):
    """A circuit's path, built live from the aggregator proxy (identity/labels come from the WFO)."""

    connection_id: str | None = None
    segments: list[PathSegment] = []


class CircuitOnSdp(BaseModel):
    """A circuit as shown under one SDP in the spectrum drill-in."""

    subscription_id: str | None = None  # WFO id, for linking to the circuit detail page
    description: str | None = None
    connection_id: str | None = None
    vlan: str | None = None
    capacity: int | None = None
    status: str | None = None


class SpectrumRow(BaseModel):
    """One SDP with the circuits crossing it (a /spectrum row)."""

    subscription_id: str | None = None
    sdp_name: str | None = None
    stp_a: str | None = None
    stp_z: str | None = None
    circuit_count: int = 0
    total_capacity: int = 0
    circuits: list[CircuitOnSdp] = []


class SpectrumView(BaseModel):
    """The /spectrum result: SDP rows, or an ``error`` if a source could not be reached."""

    rows: list[SpectrumRow] = []
    error: str | None = None


UNATTRIBUTED_ID = "unattributed"


def _vlan_of(raw: str | None) -> str | None:
    """Return the ``?vlan=`` value of an STP URN, or ``None`` if absent."""
    if not raw or "?" not in raw:
        return None
    query = raw.split("?", 1)[1]
    params = dict(param.split("=", 1) for param in query.split("&") if "=" in param)
    return params.get("vlan")


def _map_segment(seg: dict) -> PathSegment:
    return PathSegment(
        order=seg.get("order"),
        source_stp=seg.get("sourceSTP"),
        dest_stp=seg.get("destSTP"),
        capacity=seg.get("capacity"),
        provider_nsa=seg.get("providerNSA"),
        status=seg.get("status"),
    )


def _map_circuit(circuit: dict) -> AggCircuit:
    return AggCircuit(
        connection_id=circuit.get("connectionId"),
        segments=[_map_segment(seg) for seg in (circuit.get("segments") or []) if isinstance(seg, dict)],
    )


def fetch_agg_circuits() -> list[AggCircuit] | None:
    """Fetch all reservations with their path segments from the aggregator proxy, or ``None`` on failure."""
    url = HttpUrl(f"{str(settings.NSI_AGG_PROXY_URL).rstrip('/')}/reservations")
    raw = nsi_util_get_json(url, {"detail": "full"})
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("cannot parse aggregator response", error=str(e))
        return None
    if not isinstance(data, dict) or not isinstance(data.get("reservations"), list):
        logger.warning("aggregator response has no reservations list")
        return None
    return [_map_circuit(reservation) for reservation in data["reservations"] if isinstance(reservation, dict)]


def _touched(circuit: AggCircuit) -> set[str]:
    """Return the normalised STP ids the circuit's path touches (both ends of every segment)."""
    return {nid for raw in _segment_ends(circuit) if (nid := normalize_stp_id(raw))}


def _segment_ends(circuit: AggCircuit) -> Iterator[str | None]:
    """Yield the source and dest STP of every segment in the circuit's path."""
    return (raw for seg in circuit.segments for raw in (seg.source_stp, seg.dest_stp))


def _vlan_on_sdp(circuit: AggCircuit, pair: frozenset[str]) -> str | None:
    """Best-effort VLAN of the circuit at this SDP: the vlan on a segment end that is an SDP member."""
    return next(
        (vlan for raw in _segment_ends(circuit) if normalize_stp_id(raw) in pair and (vlan := _vlan_of(raw))), None
    )


# A WFO-backed circuit: its authoritative WFO record paired with the aggregator path it maps to.
_Backed = tuple[AggCircuit, CircuitRow]


def _circuit_on_sdp(agg: AggCircuit, wfo: CircuitRow, pair: frozenset[str] | None = None) -> CircuitOnSdp:
    """Build a drill-in row: identity/label/capacity from the authoritative WFO circuit, VLAN from the path.

    ``pair`` is the SDP the circuit crosses; when ``None`` (the unattributed bucket) there is no
    per-SDP VLAN to resolve.
    """
    return CircuitOnSdp(
        subscription_id=wfo.subscription_id,
        description=wfo.description,
        connection_id=wfo.connection_id,
        vlan=_vlan_on_sdp(agg, pair) if pair else None,
        capacity=wfo.bandwidth,
        status=wfo.state,
    )


def _spectrum_row(sdp: SdpSub, pair: frozenset[str], members: list[_Backed]) -> SpectrumRow:
    stp_a, stp_z = tuple(sorted(pair))
    return SpectrumRow(
        subscription_id=sdp.subscription_id,
        sdp_name=sdp.sdp_name,
        stp_a=stp_a,
        stp_z=stp_z,
        circuit_count=len(members),
        total_capacity=sum(wfo.bandwidth or 0 for _agg, wfo in members),
        circuits=[_circuit_on_sdp(agg, wfo, pair) for agg, wfo in members],
    )


def _unattributed_row(members: list[_Backed]) -> SpectrumRow:
    return SpectrumRow(
        subscription_id=UNATTRIBUTED_ID,
        sdp_name="Unattributed circuits",
        circuit_count=len(members),
        total_capacity=sum(wfo.bandwidth or 0 for _agg, wfo in members),
        circuits=[_circuit_on_sdp(agg, wfo) for agg, wfo in members],
    )


def _wfo_backed_pairs(agg_circuits: list[AggCircuit], wfo_circuits: list[CircuitRow]) -> list[_Backed]:
    """Pair each aggregator circuit with its non-terminated WFO circuit, matched by connection id.

    The orchestrator is the source of truth: aggregator circuits without a matching non-terminated WFO
    subscription are dropped (old circuits not created through the orchestrator), and the ones kept take
    all their display fields from the WFO. Any WFO-vs-aggregator drift is flagged by a separate WFO
    validation workflow, not surfaced here.
    """
    wfo_by_conn = {
        circuit.connection_id: circuit
        for circuit in wfo_circuits
        if circuit.connection_id and circuit_state_bucket(circuit.state) != "terminated"
    }
    return [(agg, wfo_by_conn[agg.connection_id]) for agg in agg_circuits if agg.connection_id in wfo_by_conn]


def build_spectrum(
    sdps: list[SdpSub] | None, agg_circuits: list[AggCircuit] | None, wfo_circuits: list[CircuitRow] | None
) -> SpectrumView:
    """Group the WFO-backed circuits by the SDP they cross.

    Only aggregator circuits with a non-terminated WFO subscription are considered, and each shows its
    authoritative WFO fields (see ``_wfo_backed_pairs``) — only the per-SDP VLAN comes from the path. A
    circuit is *on* SDP{A,Z} when both normalised STP ids appear among the STPs its path touches
    (``pair <= touched``); this matches whether the aggregator models the inter-domain fiber as its own
    segment or as the boundary between two within-domain segments. Multi-segment circuits that match no
    known SDP are collected under a single "Unattributed circuits" row so gaps stay visible. If any
    source could not be reached (``None``, not empty) the whole view is an error — a grouping computed
    from a failed fetch would misreport every SDP.
    """
    if sdps is None or agg_circuits is None or wfo_circuits is None:
        return SpectrumView(error="Spectrum unavailable: the aggregator proxy or WFO could not be reached.")
    backed = _wfo_backed_pairs(agg_circuits, wfo_circuits)
    touched = [_touched(agg) for agg, _wfo in backed]
    pairs = sorted(
        ((sdp, pair) for sdp in sdps if (pair := sdp_pair(member.stp_id for member in sdp.stps))),
        key=lambda sdp_pair: tuple(sorted(sdp_pair[1])),
    )
    rows = [
        _spectrum_row(sdp, pair, [pairing for pairing, t in zip(backed, touched) if pair <= t]) for sdp, pair in pairs
    ]
    known = [pair for _, pair in pairs]
    unattributed = [
        (agg, wfo)
        for (agg, wfo), t in zip(backed, touched)
        if len(agg.segments) > 1 and not any(pair <= t for pair in known)
    ]
    if unattributed:
        rows.append(_unattributed_row(unattributed))
    return SpectrumView(rows=rows)
