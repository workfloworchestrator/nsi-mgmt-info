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

from unittest.mock import patch

import pytest

from amiss import data
from amiss.sources import wfo
from amiss.sources.aggregator import AggCircuit, PathSegment
from amiss.sources.reconcile import DdsSdp, DdsStp, ReconcileStatus
from amiss.sources.wfo import CircuitRow, SdpMember, SdpSub, StpSub, WfoUnauthorizedError


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


def test_get_spectrum_never_raises_on_source_error():
    with (
        patch.object(data, "fetch_sdp_subscriptions", return_value=[]),
        patch.object(data, "fetch_circuits", return_value=[]),
        patch.object(data, "fetch_agg_circuits", side_effect=RuntimeError("mTLS misconfig")),
    ):
        assert data.get_spectrum("tok").error is not None


@pytest.mark.parametrize(
    ("agg_return", "connection_id", "expected_orders"),
    [
        pytest.param([AggCircuit(connection_id="c1", segments=[PathSegment(order=0)])], "c1", [0], id="match"),
        pytest.param([AggCircuit(connection_id="c1", segments=[PathSegment(order=0)])], "other", [], id="no-match"),
        pytest.param([], "c1", [], id="empty"),
    ],
)
def test_get_circuit_path_returns_matching_segments(agg_return, connection_id, expected_orders):
    with patch.object(data, "fetch_agg_circuits", return_value=agg_return):
        segments = data.get_circuit_path(connection_id)
    assert [segment.order for segment in segments] == expected_orders


@pytest.mark.parametrize(
    "fetch_kwargs",
    [
        pytest.param({"return_value": None}, id="aggregator-unreachable"),
        pytest.param({"side_effect": RuntimeError("boom")}, id="never-raises"),
    ],
)
def test_get_circuit_path_none_on_failure(fetch_kwargs):
    with patch.object(data, "fetch_agg_circuits", **fetch_kwargs):
        assert data.get_circuit_path("c1") is None


def test_get_circuits_never_raises_on_source_error():
    with patch.object(data, "fetch_circuits", side_effect=RuntimeError("mTLS misconfig")):
        assert "could not be reached" in data.get_circuits("tok").error


@pytest.mark.parametrize("accessor", ["get_circuits", "get_stps", "get_sdps", "get_spectrum"])
def test_refused_credentials_are_reported_as_not_authorized(accessor):
    # Patch query_wfo, not the individual fetches: every WFO fetch funnels through it, so an
    # accessor's other fetches cannot escape to the network and cost a real DNS lookup.
    with patch.object(wfo, "query_wfo", side_effect=WfoUnauthorizedError):
        assert getattr(data, accessor)("tok").error == data.NOT_AUTHORIZED


@pytest.mark.parametrize(
    ("getter", "fetch_name"),
    [
        pytest.param(data.get_stps, "fetch_stp_subscriptions", id="stp"),
        pytest.param(data.get_sdps, "fetch_sdp_subscriptions", id="sdp"),
    ],
)
def test_reconcile_getter_never_raises_on_source_error(getter, fetch_name):
    with patch.object(data, fetch_name, side_effect=RuntimeError("mTLS misconfig")):
        result = getter("tok")
    assert result.error is not None and result.rows == []
