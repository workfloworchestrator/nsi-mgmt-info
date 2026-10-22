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

"""Tests for amiss.data: the accessor that composes WFO + DDS fetches into rows (mocked sources)."""

from contextlib import ExitStack
from unittest.mock import patch

import pytest

from amiss import data
from amiss.sources import wfo
from amiss.sources.aggregator import AggCircuit, PathSegment
from amiss.sources.providers import PROVIDERS_UNAVAILABLE, DdsNsa, Upa, UpaReservation
from amiss.sources.reconcile import DdsNamed, DdsSdp, DdsStp, ReconcileStatus
from amiss.sources.wfo import CircuitRow, SdpMember, SdpSub, StpSub, WfoUnauthorizedError

# Every accessor that reaches the WFO and returns a rows/error model.
_ACCESSORS = ["get_circuits", "get_stps", "get_sdps", "get_spectrum"]

_SUPA = "urn:ogf:network:surf.nl:2020:nsa:supa"


def test_get_circuits_passthrough():
    rows = [CircuitRow(subscription_id="c1")]
    with patch.object(data, "fetch_circuits", return_value=rows):
        result = data.get_circuits("tok")
    assert result.rows == rows and result.error is None


def test_get_circuits_error_on_failure():
    with patch.object(data, "fetch_circuits", return_value=None):
        result = data.get_circuits("tok")
    assert result.rows == [] and "could not be reached" in result.error


def test_get_stps_reconciles():
    wfo = [StpSub(subscription_id="s", stp_id="urn:ogf:network:x")]
    dds = [DdsStp(stp_id="x")]
    with (
        patch.object(data, "fetch_stp_subscriptions", return_value=wfo),
        patch.object(data, "fetch_dds_stps", return_value=dds),
    ):
        result = data.get_stps("tok")
    assert result.error is None
    assert [r.status for r in result.rows] == [ReconcileStatus.IN_BOTH]


def test_get_stps_source_failure_yields_error():
    with (
        patch.object(data, "fetch_stp_subscriptions", return_value=None),
        patch.object(data, "fetch_dds_stps", return_value=[]),
    ):
        assert data.get_stps("tok").error is not None


def test_get_sdps_reconciles():
    wfo = [
        SdpSub(subscription_id="d", stps=[SdpMember(stp_id="urn:ogf:network:a"), SdpMember(stp_id="urn:ogf:network:b")])
    ]
    dds = [DdsSdp(stp_a_id="a", stp_z_id="b")]
    with (
        patch.object(data, "fetch_sdp_subscriptions", return_value=wfo),
        patch.object(data, "fetch_dds_sdps", return_value=dds),
    ):
        result = data.get_sdps("tok")
    assert result.error is None
    assert [r.status for r in result.rows] == [ReconcileStatus.IN_BOTH]


def test_get_spectrum_groups_circuits_by_sdp():
    sdps = [
        SdpSub(
            subscription_id="d1",
            sdp_name="A<->B",
            stps=[SdpMember(stp_id="urn:ogf:network:dom:a"), SdpMember(stp_id="urn:ogf:network:dom:b")],
        )
    ]
    agg_circuits = [
        AggCircuit(connection_id="c1", segments=[PathSegment(source_stp="dom:a?vlan=5", dest_stp="dom:b?vlan=5")])
    ]
    with (
        patch.object(data, "fetch_sdp_subscriptions", return_value=sdps),
        patch.object(data, "fetch_agg_circuits", return_value=agg_circuits),
        patch.object(
            data,
            "fetch_circuits",
            return_value=[CircuitRow(subscription_id="s1", connection_id="c1", state="ACTIVATED")],
        ),
    ):
        result = data.get_spectrum("tok")
    assert result.error is None
    assert result.rows[0].subscription_id == "d1" and result.rows[0].circuit_count == 1


def test_get_spectrum_source_failure_yields_error():
    with (
        patch.object(data, "fetch_sdp_subscriptions", return_value=None),
        patch.object(data, "fetch_agg_circuits", return_value=[]),
        patch.object(data, "fetch_circuits", return_value=[]),
    ):
        assert data.get_spectrum("tok").error is not None


def test_get_spectrum_never_raises_on_aggregator_error():
    """The aggregator is the one non-WFO source an accessor can fail on."""
    with (
        patch.object(data, "fetch_sdp_subscriptions", return_value=[]),
        patch.object(data, "fetch_circuits", return_value=[]),
        patch.object(data, "fetch_agg_circuits", side_effect=RuntimeError("mTLS misconfig")),
    ):
        assert data.get_spectrum("tok").error is not None


_CROSSING = SdpSub(
    subscription_id="d1",
    stps=[SdpMember(stp_id="urn:ogf:network:dom:a"), SdpMember(stp_id="urn:ogf:network:dom:b")],
)

_CIRCUIT_SOURCES = {
    "fetch_circuits": {"return_value": [CircuitRow(subscription_id="s1", connection_id="c1", state="ACTIVATED")]},
    "fetch_sdp_subscriptions": {"return_value": [_CROSSING]},
    "fetch_stp_subscriptions": {"return_value": [StpSub(subscription_id="stp-a", stp_id="urn:ogf:network:dom:a")]},
    "fetch_agg_circuits": {
        "return_value": [
            AggCircuit(
                connection_id="c1", segments=[PathSegment(order=0, source_stp="dom:a?vlan=5", dest_stp="dom:b?vlan=5")]
            )
        ]
    },
}


def _circuit_detail(subscription_id="s1", **overrides):
    """Run get_circuit_detail with every source patched; overrides are patch kwargs per fetch."""
    with ExitStack() as stack:
        for name, kwargs in (_CIRCUIT_SOURCES | overrides).items():
            stack.enter_context(patch.object(data, name, **kwargs))
        return data.get_circuit_detail("tok", subscription_id)


def test_get_circuit_detail_links_the_path_and_the_sdps_crossed():
    detail = _circuit_detail()
    assert detail.circuit.subscription_id == "s1"
    [segment] = detail.path
    # dom:a is a WFO STP subscription; dom:b is not, so that end stays unlinked
    assert (segment.source_stp_subscription_id, segment.dest_stp_subscription_id) == ("stp-a", None)
    assert [sdp.subscription_id for sdp in detail.sdps] == ["d1"]


@pytest.mark.parametrize(
    ("overrides", "path", "sdps"),
    [
        pytest.param({"fetch_agg_circuits": {"return_value": None}}, None, None, id="aggregator-unreachable"),
        pytest.param({"fetch_agg_circuits": {"side_effect": RuntimeError("boom")}}, None, None, id="never-raises"),
        pytest.param({"fetch_agg_circuits": {"return_value": []}}, [], [], id="no-reservation"),
        pytest.param({"fetch_sdp_subscriptions": {"return_value": None}}, [0], None, id="sdps-unavailable"),
        pytest.param({"fetch_stp_subscriptions": {"return_value": None}}, [0], ["d1"], id="stps-only-drop-links"),
    ],
)
def test_get_circuit_detail_degrades_per_section(overrides, path, sdps):
    detail = _circuit_detail(**overrides)
    assert detail.error is None and detail.circuit is not None
    assert (None if detail.path is None else [segment.order for segment in detail.path]) == path
    assert (None if detail.sdps is None else [sdp.subscription_id for sdp in detail.sdps]) == sdps


@pytest.mark.parametrize(
    ("subscription_id", "overrides", "error"),
    [
        pytest.param("nope", {}, None, id="unknown-circuit"),
        pytest.param("s1", {"fetch_circuits": {"return_value": None}}, "could not be reached", id="wfo-down"),
        pytest.param(
            "s1", {"fetch_stp_subscriptions": {"side_effect": WfoUnauthorizedError}}, data.NOT_AUTHORIZED, id="refused"
        ),
    ],
)
def test_get_circuit_detail_without_a_circuit(subscription_id, overrides, error):
    detail = _circuit_detail(subscription_id, **overrides)
    assert detail.circuit is None
    assert (error in detail.error) if error else detail.error is None


def test_get_topologies_links_the_serving_provider():
    with (
        patch.object(data, "fetch_topology_subscriptions", return_value=[]),
        patch.object(data, "fetch_dds_topologies", return_value=[DdsNamed(object_id="urn:ogf:network:dom:topo")]),
        patch.object(data, "fetch_providers", return_value=[Upa(nsa_id=_SUPA, network_ids=["dom:topo"])]),
        patch.object(data, "fetch_dds_nsas", return_value=[DdsNsa(nsa_id=_SUPA, name="SURF")]),
    ):
        [row] = data.get_topologies("tok").rows
    assert (row.provider_nsa, row.provider_name) == (_SUPA, "SURF")


def test_get_topologies_renders_without_the_providers():
    with (
        patch.object(data, "fetch_topology_subscriptions", return_value=[]),
        patch.object(data, "fetch_dds_topologies", return_value=[DdsNamed(object_id="dom:topo")]),
        patch.object(data, "fetch_providers", return_value=None),
        patch.object(data, "fetch_dds_nsas", return_value=[]),
    ):
        result = data.get_topologies("tok")
    assert result.error is None and result.rows[0].provider_nsa is None


# Patch query_wfo rather than the individual fetches: every WFO fetch funnels through it, so an
# accessor's other fetches cannot escape to the network and cost a real DNS lookup.
@pytest.mark.parametrize("accessor", _ACCESSORS)
def test_accessors_never_raise_on_source_error(accessor):
    """The accessors back user-facing pages, so an unexpected source error degrades, never 500s."""
    with patch.object(wfo, "query_wfo", side_effect=RuntimeError("mTLS misconfig")):
        result = getattr(data, accessor)("tok")
    assert result.error is not None and result.rows == []


_PROVIDER_SOURCES = {
    "fetch_providers": {"return_value": [Upa(nsa_id=_SUPA)]},
    "fetch_dds_nsas": {"return_value": []},
    "fetch_provider_reservations": {
        "return_value": [UpaReservation(connection_id="child-1", global_reservation_id="urn:uuid:1")]
    },
    "fetch_circuits": {"return_value": [CircuitRow(subscription_id="sub-1", global_reservation_id="urn:uuid:1")]},
    "fetch_stp_subscriptions": {"return_value": []},
}


def _provider_detail(**overrides):
    """Run get_provider_detail with every source patched; overrides are patch kwargs per fetch."""
    with ExitStack() as stack:
        for name, kwargs in (_PROVIDER_SOURCES | overrides).items():
            stack.enter_context(patch.object(data, name, **kwargs))
        return data.get_provider_detail("tok", _SUPA)


def test_get_provider_detail_links_the_circuit():
    detail = _provider_detail()
    assert detail.provider.nsa_id == _SUPA
    assert [row.subscription_id for row in detail.reservations] == ["sub-1"]


@pytest.mark.parametrize(
    ("overrides", "has_provider", "error", "has_reservations"),
    [
        pytest.param({"fetch_circuits": {"return_value": None}}, True, None, True, id="wfo-down-only-drops-links"),
        pytest.param({"fetch_provider_reservations": {"return_value": None}}, True, None, False, id="upa-down"),
        pytest.param({"fetch_providers": {"return_value": [Upa(nsa_id="other")]}}, False, None, False, id="unknown"),
        pytest.param(
            {"fetch_providers": {"return_value": None}}, False, PROVIDERS_UNAVAILABLE, False, id="aggregator-down"
        ),
        pytest.param(
            {"fetch_circuits": {"side_effect": WfoUnauthorizedError}}, False, data.NOT_AUTHORIZED, False, id="refused"
        ),
        pytest.param(
            {"fetch_dds_nsas": {"side_effect": RuntimeError("boom")}},
            False,
            "Provider unavailable",
            False,
            id="never-raises",
        ),
    ],
)
def test_get_provider_detail_degrades(overrides, has_provider, error, has_reservations):
    detail = _provider_detail(**overrides)
    assert (detail.provider is not None, detail.error, detail.reservations is not None) == (
        has_provider,
        error,
        has_reservations,
    )


@pytest.mark.parametrize(
    ("fetch_kwargs", "expected_error"),
    [
        pytest.param({"return_value": [Upa(nsa_id=_SUPA)]}, None, id="joined"),
        pytest.param({"side_effect": RuntimeError("boom")}, PROVIDERS_UNAVAILABLE, id="never-raises"),
    ],
)
def test_get_providers(fetch_kwargs, expected_error):
    with (
        patch.object(data, "fetch_providers", **fetch_kwargs),
        patch.object(data, "fetch_dds_nsas", return_value=[DdsNsa(nsa_id=_SUPA, name="SURF")]),
    ):
        assert data.get_providers().error == expected_error


@pytest.mark.parametrize("accessor", _ACCESSORS)
def test_refused_credentials_are_reported_as_not_authorized(accessor):
    with patch.object(wfo, "query_wfo", side_effect=WfoUnauthorizedError):
        assert getattr(data, accessor)("tok").error == data.NOT_AUTHORIZED
