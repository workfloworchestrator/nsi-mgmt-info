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

"""Tests for amiss.sources.aggregator: JSON->DTO mapping and SDP grouping (mocked HTTP)."""

import json
from unittest.mock import patch

import pytest

from amiss.sources import aggregator as agg
from amiss.sources.aggregator import UNATTRIBUTED_ID, AggCircuit, PathSegment, build_spectrum, fetch_agg_circuits
from amiss.sources.wfo import CircuitRow, SdpMember, SdpSub


def _wfo(connection_id, state="ACTIVATED", description=None, bandwidth=None):
    """A non-terminated (by default) WFO circuit backing an aggregator reservation, matched by connection id."""
    return CircuitRow(
        subscription_id=f"s-{connection_id}",
        connection_id=connection_id,
        state=state,
        description=description,
        bandwidth=bandwidth,
    )


def _agg(connection_id, sample):
    """An aggregator circuit built from one of the raw reservation samples below."""
    return AggCircuit(
        connection_id=connection_id,
        segments=[PathSegment(source_stp=seg["sourceSTP"], dest_stp=seg["destSTP"]) for seg in sample["segments"]],
    )


# A three-segment multi-domain path: the middle segment is the inter-domain fiber, whose two ends
# (manlan.moxy-1, netherlight.moxy-1) are the crossing SDP's STPs. Segment ids carry no urn prefix
# (stripped by the aggregator) but do carry ?vlan=.
AMS_NYC = {
    "connectionId": "conn-1",
    "description": "AMS-NYC",
    "criteria": {"p2ps": {"capacity": 1000}},
    "status": "ACTIVATED",
    "segments": [
        {"order": 0, "providerNSA": "nsa-a", "capacity": 1000, "status": "ACTIVATED",
         "sourceSTP": "internet2.edu:2025:ana:manlan.ps1",
         "destSTP": "internet2.edu:2025:ana:manlan.moxy-1?vlan=481"},
        {"order": 1, "providerNSA": "nsa-link", "capacity": 1000, "status": "ACTIVATED",
         "sourceSTP": "internet2.edu:2025:ana:manlan.moxy-1?vlan=481",
         "destSTP": "surf.nl:2020:ana:netherlight.moxy-1?vlan=481"},
        {"order": 2, "providerNSA": "nsa-z", "capacity": 1000, "status": "ACTIVATED",
         "sourceSTP": "surf.nl:2020:ana:netherlight.moxy-1?vlan=481",
         "destSTP": "surf.nl:2020:ana:netherlight.ps1"},
    ],
}  # fmt: skip

# The SDP that AMS-NYC crosses; member ids come from the WFO in full urn form.
MOXY_SDP = SdpSub(
    subscription_id="d1",
    sdp_name="MANLAN<->NetherLight",
    stps=[
        SdpMember(stp_id="urn:ogf:network:internet2.edu:2025:ana:manlan.moxy-1"),
        SdpMember(stp_id="urn:ogf:network:surf.nl:2020:ana:netherlight.moxy-1"),
    ],
)

# A circuit crossing an STP pair that no known SDP covers.
ORPHAN = {
    "connectionId": "conn-2",
    "description": "orphan",
    "criteria": {"p2ps": {"capacity": 500}},
    "status": "ACTIVATED",
    "segments": [
        {"order": 0, "sourceSTP": "a.edu:2025:portX", "destSTP": "a.edu:2025:portEdge?vlan=7"},
        {"order": 1, "sourceSTP": "b.edu:2025:portEdge?vlan=7", "destSTP": "b.edu:2025:portY"},
    ],
}


class TestFetch:
    def test_maps_circuit_and_segments(self):
        with patch.object(agg, "nsi_util_get_json", return_value=json.dumps({"reservations": [AMS_NYC]}).encode()):
            circuits = fetch_agg_circuits()
        assert len(circuits) == 1
        circuit = circuits[0]
        assert circuit.connection_id == "conn-1"
        assert [seg.provider_nsa for seg in circuit.segments] == ["nsa-a", "nsa-link", "nsa-z"]
        assert circuit.segments[1].source_stp == "internet2.edu:2025:ana:manlan.moxy-1?vlan=481"

    def test_tolerates_missing_blocks(self):
        with patch.object(agg, "nsi_util_get_json", return_value=json.dumps({"reservations": [{}]}).encode()):
            circuits = fetch_agg_circuits()
        assert circuits[0].connection_id is None and circuits[0].segments == []

    @pytest.mark.parametrize(
        "raw",
        [
            pytest.param(None, id="fetch-failed"),
            pytest.param(b"<html>", id="non-json"),
            pytest.param(b"[]", id="not-an-object"),
            pytest.param(b'{"foo": 1}', id="no-reservations-key"),
        ],
    )
    def test_returns_none_on_failure(self, raw):
        with patch.object(agg, "nsi_util_get_json", return_value=raw):
            assert fetch_agg_circuits() is None


class TestBuildSpectrum:
    def test_attributes_circuit_and_uses_wfo_fields_with_path_vlan(self):
        # the WFO is authoritative for identity/label/capacity; only the VLAN comes from the path
        circuit = _agg("conn-1", AMS_NYC)
        wfo = _wfo("conn-1", description="fresh-wfo-desc", bandwidth=1000)
        view = build_spectrum([MOXY_SDP], [circuit], [wfo])
        assert view.error is None and len(view.rows) == 1
        sdp = view.rows[0]
        assert sdp.subscription_id == "d1" and sdp.circuit_count == 1
        assert sdp.total_capacity == 1000  # from WFO bandwidth, not the aggregator capacity
        # normalized pair sorted -> stp_a/stp_z; MOXY_SDP's members are unnamed, so the id shows
        assert sdp.stp_a == "internet2.edu:2025:ana:manlan.moxy-1"
        # WFO wins for description; VLAN still comes from the crossing segment end
        assert sdp.circuits[0].description == "fresh-wfo-desc"
        assert sdp.circuits[0].connection_id == "conn-1" and sdp.circuits[0].vlan == "481"
        assert sdp.circuits[0].subscription_id == "s-conn-1"  # carries the WFO id for the cross-link
        assert sdp.circuits[0].bandwidth == 1000  # from the WFO, not the aggregator segment capacity

    def test_ends_are_shown_by_name_where_the_wfo_has_one(self):
        named = MOXY_SDP.model_copy(
            update={
                "stps": [
                    member.model_copy(update={"stp_name": f"Port {index}"})
                    for index, member in enumerate(MOXY_SDP.stps)
                ]
            }
        )
        circuit = _agg("conn-1", AMS_NYC)
        row = build_spectrum([named], [circuit], [_wfo("conn-1")]).rows[0]
        assert {row.stp_a, row.stp_z} == {"Port 0", "Port 1"}

    @pytest.mark.parametrize(
        ("member_capacity", "reserved", "expected"),
        [
            pytest.param(4000, 1000, 25, id="quarter-full"),
            pytest.param(1000, 1000, 100, id="full"),
            pytest.param(None, 1000, None, id="link-capacity-unknown"),
            pytest.param(0, 1000, None, id="link-capacity-zero"),
        ],
    )
    def test_utilisation_is_the_percentage_of_the_link_reserved(self, member_capacity, reserved, expected):
        sdp = MOXY_SDP.model_copy(
            update={"stps": [member.model_copy(update={"capacity": member_capacity}) for member in MOXY_SDP.stps]}
        )
        circuit = _agg("conn-1", AMS_NYC)
        row = build_spectrum([sdp], [circuit], [_wfo("conn-1", bandwidth=reserved)]).rows[0]
        assert row.utilisation == expected

    def test_circuit_only_touching_one_end_is_not_attributed(self):
        # touches manlan.moxy-1 but not netherlight.moxy-1 -> not on the SDP (subset test, not "any end")
        circuit = AggCircuit(
            connection_id="conn-1",
            segments=[
                PathSegment(
                    source_stp="internet2.edu:2025:ana:manlan.ps1", dest_stp="internet2.edu:2025:ana:manlan.moxy-1"
                ),
            ],
        )
        view = build_spectrum([MOXY_SDP], [circuit], [_wfo("conn-1")])
        assert view.rows[0].circuit_count == 0
        # single-segment circuit is not collected as unattributed either
        assert not any(row.subscription_id == UNATTRIBUTED_ID for row in view.rows)

    def test_multi_segment_circuit_on_no_known_sdp_is_unattributed(self):
        circuit = _agg("conn-2", ORPHAN)
        view = build_spectrum([MOXY_SDP], [circuit], [_wfo("conn-2", bandwidth=500)])
        unattributed = next(row for row in view.rows if row.subscription_id == UNATTRIBUTED_ID)
        assert unattributed.circuit_count == 1 and unattributed.total_capacity == 500
        assert view.rows[0].circuit_count == 0  # the known SDP has none

    @pytest.mark.parametrize(
        ("wfo", "expected_count"),
        [
            pytest.param([_wfo("conn-1", "ACTIVATED")], 1, id="activated-shown"),
            pytest.param([_wfo("conn-1", "FAILED")], 1, id="failed-shown"),
            pytest.param([_wfo("conn-1", "TERMINATED")], 0, id="terminated-hidden"),
            pytest.param([_wfo("other")], 0, id="no-matching-subscription-hidden"),
            pytest.param([], 0, id="no-wfo-circuits-hidden"),
        ],
    )
    def test_only_non_terminated_wfo_backed_circuits_are_shown(self, wfo, expected_count):
        circuit = _agg("conn-1", AMS_NYC)
        view = build_spectrum([MOXY_SDP], [circuit], wfo)
        assert view.rows[0].circuit_count == expected_count

    @pytest.mark.parametrize(
        ("sdps", "agg_circuits", "wfo"),
        [
            pytest.param(None, [], [], id="sdps-failed"),
            pytest.param([], None, [], id="aggregator-failed"),
            pytest.param([], [], None, id="wfo-failed"),
        ],
    )
    def test_source_failure_yields_error_no_rows(self, sdps, agg_circuits, wfo):
        view = build_spectrum(sdps, agg_circuits, wfo)
        assert view.error is not None and view.rows == []
