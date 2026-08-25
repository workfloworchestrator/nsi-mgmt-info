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

"""Tests for amiss.sources.reconcile: WFO-subscription vs DDS-topology diffing."""

import pytest

from amiss.sources.reconcile import (
    DdsNamed,
    DdsSdp,
    DdsStp,
    ReconcileStatus,
    StpRow,
    normalize_id,
    reconcile_named,
    reconcile_sdps,
    reconcile_stps,
    sdp_capacity,
)
from amiss.sources.wfo import NamedSub, SdpMember, SdpSub, StpSub


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("urn:ogf:network:dom:2025:portA", "dom:2025:portA", id="strips-urn-prefix"),
        pytest.param("dom:2025:portA?vlan=100", "dom:2025:portA", id="strips-vlan-suffix"),
        pytest.param("urn:ogf:network:dom:2025:portA?vlan=100", "dom:2025:portA", id="strips-both"),
        pytest.param("  dom:2025:portA  ", "dom:2025:portA", id="strips-whitespace"),
        pytest.param("dom:2025:PortA", "dom:2025:PortA", id="preserves-case"),
        pytest.param(None, None, id="none"),
        pytest.param("", None, id="empty"),
    ],
)
def test_normalize_id(raw, expected):
    assert normalize_id(raw) == expected


class TestReconcileStps:
    def test_classifies_each_stp(self):
        wfo = [
            StpSub(subscription_id="s-a", stp_id="urn:ogf:network:dom:portA", stp_name="A", label_group="1-10"),
            StpSub(subscription_id="s-c", stp_id="urn:ogf:network:dom:portC", stp_name="C"),
        ]
        dds = [
            DdsStp(stp_id="dom:portA", vlan_range="1-10", description="A from dds"),
            DdsStp(stp_id="dom:portB", vlan_range="1-20", description="B from dds"),
        ]
        by_status = {row.status: row for row in reconcile_stps(wfo, dds).rows}

        assert set(by_status) == {
            ReconcileStatus.IN_BOTH,
            ReconcileStatus.DDS_ONLY,
            ReconcileStatus.MISSING_IN_DDS,
        }
        # backed by DDS: DDS display fields win, subscription id present
        in_both = by_status[ReconcileStatus.IN_BOTH]
        assert in_both.stp_id == "dom:portA" and in_both.description == "A from dds"
        assert in_both.subscription_id == "s-a"
        # DDS-only: no subscription
        assert by_status[ReconcileStatus.DDS_ONLY].subscription_id is None
        # subscription not in DDS: keeps the WFO id, flagged
        assert by_status[ReconcileStatus.MISSING_IN_DDS].subscription_id == "s-c"

    def test_carries_the_wfo_capacity_and_lifecycle_status(self):
        wfo = [StpSub(subscription_id="s-a", stp_id="dom:portA", capacity=100000, status="active")]
        row = reconcile_stps(wfo, [DdsStp(stp_id="dom:portA")]).rows[0]
        assert row.capacity == 100000 and row.wfo_status == "active"

    @pytest.mark.parametrize(
        ("stp_id", "network", "port"),
        [
            pytest.param("dom.example.net:2024:topo:portA", "dom.example.net:2024:topo", "portA", id="urn-style-id"),
            pytest.param("portA", None, "portA", id="no-topology-prefix"),
            pytest.param(None, None, None, id="no-id"),
        ],
    )
    def test_splits_the_topology_off_the_stp_id(self, stp_id, network, port):
        row = StpRow(stp_id=stp_id, status=ReconcileStatus.DDS_ONLY)
        assert (row.network, row.port) == (network, port)

    @pytest.mark.parametrize(
        ("subscription_id", "expected"),
        [pytest.param("abcdef12-3456", "abcdef12", id="shortened"), pytest.param(None, None, id="dds-only-row")],
    )
    def test_short_id(self, subscription_id, expected):
        assert StpRow(subscription_id=subscription_id, status=ReconcileStatus.IN_BOTH).short_id == expected

    @pytest.mark.parametrize(
        ("wfo", "dds"),
        [pytest.param(None, [], id="wfo-failed"), pytest.param([], None, id="dds-failed")],
    )
    def test_source_failure_yields_error_no_rows(self, wfo, dds):
        result = reconcile_stps(wfo, dds)
        assert result.error is not None and result.rows == []


class TestReconcileSdps:
    def test_matches_unordered_pair_ignoring_prefix_and_vlan(self):
        wfo = [
            SdpSub(
                subscription_id="sdp-1",
                sdp_name="A<->B",
                stps=[SdpMember(stp_id="urn:ogf:network:dom:portA"), SdpMember(stp_id="urn:ogf:network:dom:portB")],
            ),
            SdpSub(
                subscription_id="sdp-2",
                sdp_name="E<->F",
                stps=[SdpMember(stp_id="dom:portE"), SdpMember(stp_id="dom:portF")],
            ),
        ]
        dds = [
            # reversed order + vlan suffixes: must still match the sdp-1 pair
            DdsSdp(stp_a_id="dom:portB?vlan=100", stp_z_id="dom:portA?vlan=200"),
            DdsSdp(stp_a_id="dom:portC", stp_z_id="dom:portD"),
        ]
        by_status = {row.status: row for row in reconcile_sdps(wfo, dds).rows}

        assert set(by_status) == {
            ReconcileStatus.IN_BOTH,
            ReconcileStatus.DDS_ONLY,
            ReconcileStatus.MISSING_IN_DDS,
        }
        assert by_status[ReconcileStatus.IN_BOTH].subscription_id == "sdp-1"
        assert by_status[ReconcileStatus.MISSING_IN_DDS].subscription_id == "sdp-2"
        assert by_status[ReconcileStatus.DDS_ONLY].subscription_id is None

    def test_reads_member_values_by_id_not_by_position(self):
        """The WFO returns the members in its own order, unrelated to the A/Z order the row displays.

        Reading them positionally would print the two ends' VLAN ranges swapped against the STP A /
        STP Z columns beside them.
        """
        wfo = SdpSub(
            subscription_id="sdp-1",
            # reversed relative to the A/Z ids the DDS gives below
            stps=[
                SdpMember(stp_id="dom:portB", label_group="200-299"),
                SdpMember(stp_id="dom:portA", label_group="100-199"),
            ],
        )
        row = reconcile_sdps([wfo], [DdsSdp(stp_a_id="dom:portA", stp_z_id="dom:portB")]).rows[0]
        assert (row.stp_a_id, row.stp_z_id) == ("dom:portA", "dom:portB")
        assert row.vlan_range == "100-199 | 200-299"

    @pytest.mark.parametrize(
        ("stp_name", "expected"),
        [
            pytest.param("NetherLight to DFN 2", "NetherLight to DFN 2", id="name-when-the-wfo-has-one"),
            pytest.param(None, "dom:portA", id="falls-back-to-the-id"),
        ],
    )
    def test_ends_are_shown_by_name(self, stp_name, expected):
        """The table shows each end by name; the id stays on the row for the detail page."""
        wfo = SdpSub(
            subscription_id="sdp-1",
            stps=[SdpMember(stp_id="dom:portA", stp_name=stp_name), SdpMember(stp_id="dom:portB")],
        )
        row = reconcile_sdps([wfo], [DdsSdp(stp_a_id="dom:portA", stp_z_id="dom:portB")]).rows[0]
        assert row.stp_a_name == expected
        assert row.stp_a_id == "dom:portA"

    @pytest.mark.parametrize(
        ("label_a", "label_z", "expected"),
        [
            pytest.param("1-10", "1-10", "1-10", id="ends-agree-show-one"),
            pytest.param("1-10", "1-20", "1-10 | 1-20", id="ends-differ-show-both"),
            pytest.param("1-10", None, "1-10", id="only-one-end-known"),
            pytest.param(None, None, None, id="neither-end-known"),
        ],
    )
    def test_vlan_range_comes_from_the_members(self, label_a, label_z, expected):
        wfo = SdpSub(
            subscription_id="sdp-1",
            stps=[
                SdpMember(stp_id="dom:portA", label_group=label_a),
                SdpMember(stp_id="dom:portB", label_group=label_z),
            ],
        )
        row = reconcile_sdps([wfo], [DdsSdp(stp_a_id="dom:portA", stp_z_id="dom:portB")]).rows[0]
        assert row.vlan_range == expected

    @pytest.mark.parametrize(
        ("capacity_a", "capacity_z", "expected"),
        [
            pytest.param(100, 100, 100, id="ends-agree"),
            pytest.param(400, 100, 100, id="lower-end-binds"),
            pytest.param(None, 100, 100, id="only-one-end-known"),
            pytest.param(None, None, None, id="neither-end-known"),
        ],
    )
    def test_capacity_is_the_lower_end(self, capacity_a, capacity_z, expected):
        sdp = SdpSub(
            subscription_id="sdp-1",
            stps=[
                SdpMember(stp_id="dom:portA", capacity=capacity_a),
                SdpMember(stp_id="dom:portB", capacity=capacity_z),
            ],
        )
        assert sdp_capacity(sdp) == expected
        assert reconcile_sdps([sdp], []).rows[0].capacity == expected

    @pytest.mark.parametrize(
        ("wfo", "dds"),
        [pytest.param(None, [], id="wfo-failed"), pytest.param([], None, id="dds-failed")],
    )
    def test_source_failure_yields_error_no_rows(self, wfo, dds):
        result = reconcile_sdps(wfo, dds)
        assert result.error is not None and result.rows == []


class TestReconcileNamed:
    @pytest.mark.parametrize(
        ("wfo", "dds", "expected"),
        [
            pytest.param(
                [NamedSub(subscription_id="s", object_id="urn:ogf:network:a", name="A")],
                [DdsNamed(object_id="a", name="A")],
                ReconcileStatus.IN_BOTH,
                id="in-both-matched-across-urn-prefix",
            ),
            pytest.param(
                [],
                [DdsNamed(object_id="a", name="A")],
                ReconcileStatus.DDS_ONLY,
                id="dds-only-is-the-normal-federated-state",
            ),
            pytest.param(
                [NamedSub(subscription_id="s", object_id="urn:ogf:network:a", name="A")],
                [],
                ReconcileStatus.MISSING_IN_DDS,
                id="subscription-the-dds-dropped",
            ),
        ],
    )
    def test_status(self, wfo, dds, expected):
        rows = reconcile_named(wfo, dds, "Topology").rows
        assert [row.status for row in rows] == [expected]

    @pytest.mark.parametrize(
        ("wfo", "dds"),
        [
            pytest.param(None, [], id="wfo-unreachable"),
            pytest.param([], None, id="dds-unreachable"),
        ],
    )
    def test_a_failed_source_yields_an_error_and_no_rows(self, wfo, dds):
        # a diff computed against a failed fetch would flag the whole estate
        result = reconcile_named(wfo, dds, "Topology")
        assert result.rows == []
        assert result.error is not None and "Topology" in result.error

    def test_wfo_name_wins_because_it_is_operator_editable(self):
        # the modify workflow renames the subscription on purpose; that is not drift
        result = reconcile_named(
            [NamedSub(subscription_id="s", object_id="a", name="local label")],
            [DdsNamed(object_id="a", name="DDS name")],
            "Topology",
        )
        assert result.rows[0].description == "local label"

    def test_falls_back_to_the_dds_name_when_unsubscribed(self):
        result = reconcile_named([], [DdsNamed(object_id="a", name="DDS name")], "Topology")
        assert result.rows[0].description == "DDS name"
        assert result.rows[0].subscription_id is None and result.rows[0].short_id is None

    def test_rows_are_sorted_by_id(self):
        dds = [DdsNamed(object_id=oid) for oid in ("c", "a", "b")]
        assert [row.object_id for row in reconcile_named([], dds, "Topology").rows] == ["a", "b", "c"]
