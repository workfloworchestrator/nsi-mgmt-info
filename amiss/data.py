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

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import structlog
from pydantic import BaseModel

from amiss.sources.aggregator import (
    AggCircuit,
    PathSegment,
    SpectrumRow,
    SpectrumView,
    build_spectrum,
    fetch_agg_circuits,
    link_segments,
    sdps_crossed,
)
from amiss.sources.dds_topology import (
    fetch_dds_nsas,
    fetch_dds_sdps,
    fetch_dds_stps,
    fetch_dds_switching_services,
    fetch_dds_topologies,
)
from amiss.sources.providers import (
    PROVIDERS_UNAVAILABLE,
    ProviderDetail,
    ProviderList,
    build_providers,
    fetch_provider_reservations,
    fetch_providers,
    link_providers,
    link_reservations,
)
from amiss.sources.reconcile import (
    DdsNamed,
    NamedReconciliation,
    SdpReconciliation,
    StpReconciliation,
    reconcile_named,
    reconcile_sdps,
    reconcile_stps,
)
from amiss.sources.wfo import (
    CircuitRow,
    NamedSub,
    WfoUnauthorizedError,
    fetch_circuits,
    fetch_sdp_subscriptions,
    fetch_stp_subscriptions,
    fetch_switching_service_subscriptions,
    fetch_topology_subscriptions,
)

logger = structlog.get_logger(__name__)

# Deliberately vague about which credential problem it is: query_wfo cannot tell an expired session
# from a missing group, and naming only one sends half of those users to the wrong fix.
NOT_AUTHORIZED = (
    "Not authorized: the orchestrator refused your credentials. "
    "Your session may have expired, or your account may lack the required group."
)


class CircuitList(BaseModel):
    """The /circuits result: circuit rows, or an ``error`` if they could not be fetched."""

    rows: list[CircuitRow] = []
    error: str | None = None


# These accessors are the boundary to external systems and back the user-facing pages (incl. the
# landing dashboard), so they must never raise: any unexpected error degrades to "unavailable"
# rather than a 500. Fetch failures arrive as None/error upstream, except a refused credential,
# which raises.
def get_circuits(token: str | None) -> CircuitList:
    """Return the circuit rows, or a ``CircuitList`` carrying why they could not be fetched."""
    try:
        rows = fetch_circuits(token)
        if rows is not None:
            return CircuitList(rows=rows)
    except WfoUnauthorizedError:
        return CircuitList(error=NOT_AUTHORIZED)
    except Exception as e:
        logger.warning("fetching circuits failed", error=str(e))
    return CircuitList(error="Circuits unavailable: the WFO could not be reached.")


def _get_named(
    token: str | None,
    fetch_wfo: Callable[[str | None], list[NamedSub] | None],
    fetch_dds: Callable[[], list[DdsNamed] | None],
    what: str,
) -> NamedReconciliation:
    """Reconcile a Topology or SwitchingService, fetching both legs at once."""
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            wfo = pool.submit(fetch_wfo, token)
            dds = pool.submit(fetch_dds)
        return reconcile_named(wfo.result(), dds.result(), what)
    except WfoUnauthorizedError:
        return NamedReconciliation(error=NOT_AUTHORIZED)
    except Exception as e:
        logger.warning("reconciliation failed", what=what, error=str(e))
        return NamedReconciliation(error=f"{what} data unavailable")


def get_topologies(token: str | None) -> NamedReconciliation:
    """Return the Topology rows reconciled between the WFO subscriptions and the DDS, with their provider.

    The providers only supply links, so their failure leaves the column empty rather than failing the page.
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        topologies = pool.submit(_get_named, token, fetch_topology_subscriptions, fetch_dds_topologies, "Topology")
        providers = pool.submit(get_providers)
    return link_providers(topologies.result(), providers.result(), lambda row: row.object_id)


def get_switching_services(token: str | None) -> NamedReconciliation:
    """Return the SwitchingService rows reconciled between the WFO subscriptions and the DDS."""
    return _get_named(token, fetch_switching_service_subscriptions, fetch_dds_switching_services, "Switching service")


def get_stps(token: str | None) -> StpReconciliation:
    """Return the STP rows reconciled between the WFO subscriptions and the DDS topology (fetched concurrently)."""
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            wfo = pool.submit(fetch_stp_subscriptions, token)
            dds = pool.submit(fetch_dds_stps)
        return reconcile_stps(wfo.result(), dds.result())
    except WfoUnauthorizedError:
        return StpReconciliation(error=NOT_AUTHORIZED)
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
    except WfoUnauthorizedError:
        return SdpReconciliation(error=NOT_AUTHORIZED)
    except Exception as e:
        logger.warning("SDP reconciliation failed", error=str(e))
        return SdpReconciliation(error="SDP data unavailable")


class StpDetail(BaseModel):
    """The STP detail page's sources, each keeping its own ``error`` so the page degrades per section."""

    stps: StpReconciliation
    circuits: CircuitList
    sdps: SdpReconciliation


def get_stp_detail(token: str | None) -> StpDetail:
    """Return the reconciled STPs, linked to their provider, plus the circuits and SDPs the page lists.

    Independent legs, so the STP's own fields still render when only a related list could not be fetched;
    the providers only supply links, so their failure leaves the provider empty.
    """
    with ThreadPoolExecutor(max_workers=4) as pool:
        stps = pool.submit(get_stps, token)
        circuits = pool.submit(get_circuits, token)
        sdps = pool.submit(get_sdps, token)
        providers = pool.submit(get_providers)
    return StpDetail(
        stps=link_providers(stps.result(), providers.result(), lambda row: row.network),
        circuits=circuits.result(),
        sdps=sdps.result(),
    )


def get_sdp_detail(token: str | None) -> tuple[SdpReconciliation, SpectrumView]:
    """Return the reconciled SDP rows and the spectrum view, for the SDP detail page.

    Fetches each upstream exactly once and composes both views from the shared results (as the
    dashboard does); calling ``get_sdps`` and ``get_spectrum`` instead would issue the same SDP
    subscription query twice, and a WFO round-trip is the dominant cost of the page.
    """
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            sdp_subs = pool.submit(fetch_sdp_subscriptions, token)
            dds_sdps = pool.submit(fetch_dds_sdps)
            agg = pool.submit(fetch_agg_circuits)
            circuits = pool.submit(fetch_circuits, token)
        sdps = sdp_subs.result()
        return reconcile_sdps(sdps, dds_sdps.result()), build_spectrum(sdps, agg.result(), circuits.result())
    except WfoUnauthorizedError:
        return SdpReconciliation(error=NOT_AUTHORIZED), SpectrumView(error=NOT_AUTHORIZED)
    except Exception as e:
        logger.warning("building the SDP detail failed", error=str(e))
        return SdpReconciliation(error="SDP data unavailable"), SpectrumView(error="Spectrum unavailable")


def get_spectrum(token: str | None) -> SpectrumView:
    """Return the SDPs with the WFO-backed circuits crossing them (WFO SDPs + circuits + aggregator, concurrent)."""
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            sdps = pool.submit(fetch_sdp_subscriptions, token)
            agg = pool.submit(fetch_agg_circuits)
            circuits = pool.submit(fetch_circuits, token)
        return build_spectrum(sdps.result(), agg.result(), circuits.result())
    except WfoUnauthorizedError:
        return SpectrumView(error=NOT_AUTHORIZED)
    except Exception as e:
        logger.warning("building spectrum failed", error=str(e))
        return SpectrumView(error="Spectrum unavailable: the aggregator proxy or WFO could not be reached.")


def get_providers() -> ProviderList:
    """Return the peered uPAs joined with their DDS NSA documents (both proxies, concurrent)."""
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            upas = pool.submit(fetch_providers)
            nsas = pool.submit(fetch_dds_nsas)
        return build_providers(upas.result(), nsas.result())
    except Exception as e:
        logger.warning("fetching providers failed", error=str(e))
        return ProviderList(error=PROVIDERS_UNAVAILABLE)


def get_provider_detail(token: str | None, nsa_id: str) -> ProviderDetail:
    """Return one provider and its reservations, linked to the WFO circuits and STPs they belong to.

    The WFO only supplies links, so its failure leaves the links empty rather than failing the page. A
    refused WFO credential is still reported as such.
    """
    try:
        with ThreadPoolExecutor(max_workers=5) as pool:
            upas = pool.submit(fetch_providers)
            nsas = pool.submit(fetch_dds_nsas)
            reservations = pool.submit(fetch_provider_reservations, nsa_id)
            circuits = pool.submit(fetch_circuits, token)
            stps = pool.submit(fetch_stp_subscriptions, token)
        wfo_circuits, stp_subs = circuits.result(), stps.result()
        providers = build_providers(upas.result(), nsas.result())
        upa_reservations = reservations.result()
    except WfoUnauthorizedError:
        return ProviderDetail(error=NOT_AUTHORIZED)
    except Exception as e:
        logger.warning("building the provider detail failed", nsa_id=nsa_id, error=str(e))
        return ProviderDetail(error="Provider unavailable")
    if providers.error:
        return ProviderDetail(error=providers.error)
    provider = next((row for row in providers.rows if row.nsa_id == nsa_id), None)
    if provider is None or upa_reservations is None:
        return ProviderDetail(provider=provider)
    return ProviderDetail(
        provider=provider,
        reservations=link_reservations(upa_reservations, wfo_circuits, stp_subs),
    )


class CircuitDetail(BaseModel):
    """A circuit detail page.

    ``circuit`` is ``None`` without an ``error`` when no circuit has that id. ``path`` is ``None`` when the
    aggregator could not be reached and ``[]`` when it has no segments for the circuit; ``sdps`` is ``None``
    when the SDPs crossed could not be worked out, so the page can word "unavailable" and "none" apart.
    """

    circuit: CircuitRow | None = None
    error: str | None = None
    path: list[PathSegment] | None = None
    sdps: list[SpectrumRow] | None = None


def safe[T](fetch: Callable[..., T | None], *args: object) -> T | None:
    """Run a source fetch, degrading any unexpected error to ``None`` so a page never 500s.

    A refused credential is let through, so the page can say "not authorized" instead of "unavailable".
    """
    try:
        return fetch(*args)
    except WfoUnauthorizedError:
        raise
    except Exception as e:
        logger.warning("source fetch failed", fetch=getattr(fetch, "__name__", repr(fetch)), error=str(e))
        return None


def _circuit_path(circuit: CircuitRow, agg_circuits: list[AggCircuit] | None) -> list[PathSegment] | None:
    """Return the circuit's aggregator path segments, matched on connection id."""
    # Reuse the list fetch and filter; switch to GET /reservations/{id} if this page gets hot.
    if not circuit.connection_id:
        return []
    if agg_circuits is None:
        return None
    match = next((agg for agg in agg_circuits if agg.connection_id == circuit.connection_id), None)
    return match.segments if match else []


def get_circuit_detail(token: str | None, subscription_id: str) -> CircuitDetail:
    """Return one circuit with its aggregator path and the SDPs it crosses, linked to their WFO subscriptions.

    The aggregator uses AMISS's proxy identity (no user token). The STP subscriptions only supply links, so
    their failure leaves the path unlinked rather than failing the page.
    """
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            circuits = pool.submit(safe, fetch_circuits, token)
            sdps = pool.submit(safe, fetch_sdp_subscriptions, token)
            stps = pool.submit(safe, fetch_stp_subscriptions, token)
            agg = pool.submit(safe, fetch_agg_circuits)
        wfo_circuits, sdp_subs, stp_subs = circuits.result(), sdps.result(), stps.result()
    except WfoUnauthorizedError:
        return CircuitDetail(error=NOT_AUTHORIZED)
    if wfo_circuits is None:
        return CircuitDetail(error="Circuits unavailable: the WFO could not be reached.")
    circuit = next((row for row in wfo_circuits if row.subscription_id == subscription_id), None)
    if circuit is None:
        return CircuitDetail()
    agg_circuits = agg.result()
    path = _circuit_path(circuit, agg_circuits)
    return CircuitDetail(
        circuit=circuit,
        path=None if path is None else link_segments(path, stp_subs),
        sdps=sdps_crossed(build_spectrum(sdp_subs, agg_circuits, wfo_circuits), subscription_id),
    )
