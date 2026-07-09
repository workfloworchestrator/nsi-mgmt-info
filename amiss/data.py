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

"""Data accessor the frontend routes call to get table rows.

Queries the WFO (forwarding the caller's OIDC token) and the DDS/aggregator proxies live per request;
there is no cache. Accessors that need more than one upstream fetch them concurrently.
"""

from concurrent.futures import ThreadPoolExecutor

import structlog

from amiss.sources.aggregator import PathSegment, SpectrumView, build_spectrum, fetch_agg_circuits
from amiss.sources.dds_topology import fetch_dds_sdps, fetch_dds_stps
from amiss.sources.reconcile import SdpReconciliation, StpReconciliation, reconcile_sdps, reconcile_stps
from amiss.sources.wfo import CircuitRow, fetch_circuits, fetch_sdp_subscriptions, fetch_stp_subscriptions

logger = structlog.get_logger(__name__)


# These accessors are the boundary to external systems and back the user-facing pages (incl. the
# landing dashboard), so they must never raise: any unexpected error degrades to "unavailable"
# rather than a 500. Expected fetch failures are already turned into None/error upstream.
def get_circuits(token: str | None) -> list[CircuitRow] | None:
    """Return the circuit rows, or ``None`` if they could not be fetched."""
    try:
        return fetch_circuits(token)
    except Exception as e:
        logger.warning("fetching circuits failed", error=str(e))
        return None


def get_stps(token: str | None) -> StpReconciliation:
    """Return the STP rows reconciled between the WFO subscriptions and the DDS topology (fetched concurrently)."""
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            wfo = pool.submit(fetch_stp_subscriptions, token)
            dds = pool.submit(fetch_dds_stps)
        return reconcile_stps(wfo.result(), dds.result())
    except Exception as e:
        logger.warning("STP reconciliation failed", error=str(e))
        return StpReconciliation(error="STP data unavailable")


def get_sdps(token: str | None) -> SdpReconciliation:
    """Return the SDP rows reconciled between the WFO subscriptions and the DDS topology (fetched concurrently)."""
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            wfo = pool.submit(fetch_sdp_subscriptions, token)
            dds = pool.submit(fetch_dds_sdps)
        return reconcile_sdps(wfo.result(), dds.result())
    except Exception as e:
        logger.warning("SDP reconciliation failed", error=str(e))
        return SdpReconciliation(error="SDP data unavailable")


def get_spectrum(token: str | None) -> SpectrumView:
    """Return the SDPs with the WFO-backed circuits crossing them (WFO SDPs + circuits + aggregator, concurrent)."""
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            sdps = pool.submit(fetch_sdp_subscriptions, token)
            agg = pool.submit(fetch_agg_circuits)
            circuits = pool.submit(fetch_circuits, token)
        return build_spectrum(sdps.result(), agg.result(), circuits.result())
    except Exception as e:
        logger.warning("building spectrum failed", error=str(e))
        return SpectrumView(error="Spectrum data unavailable")


def get_circuit_path(connection_id: str | None) -> list[PathSegment] | None:
    """Return a circuit's aggregator path segments, ``None`` if the aggregator is unreachable, ``[]`` if unknown.

    The aggregator uses AMISS's proxy identity (no user token). ``None`` distinguishes "aggregator down"
    from ``[]`` ("no matching reservation / no segments") so the detail page can word the two differently.
    """
    # Reuse the list fetch and filter; switch to GET /reservations/{id} if this page gets hot.
    try:
        circuits = fetch_agg_circuits()
        if circuits is None:
            return None
        match = next((circuit for circuit in circuits if circuit.connection_id == connection_id), None)
        return match.segments if match else []
    except Exception as e:
        logger.warning("fetching circuit path failed", error=str(e))
        return None
