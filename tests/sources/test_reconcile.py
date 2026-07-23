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
    DdsSdp,
    DdsStp,
    ReconcileStatus,
    normalize_stp_id,
    reconcile_sdps,
    reconcile_stps,
)
from amiss.sources.wfo import SdpMember, SdpSub, StpSub


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
def test_normalize_stp_id(raw, expected):
    assert normalize_stp_id(raw) == expected


class TestReconcileStps:
    def test_classifies_each_stp(self):
        wfo = [
            StpSub(subscription_id="s-a", stp_id="urn:ogf:network:dom:portA", stp_name="A", label_group="1-10"),
            StpSub(subscription_id="s-c", stp_id="urn:ogf:network:dom:portC", stp_name="C"),
        ]
        dds = [
            DdsStp(
                stp_id="dom:portA", vlan_range="1-10", description="A from dds", switching_service_id="dom:switch:A"
            ),
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
        assert in_both.switching_service_id == "dom:switch:A"
        # DDS-only: no subscription
        assert by_status[ReconcileStatus.DDS_ONLY].subscription_id is None
        # subscription not in DDS: keeps the WFO id, flagged (and no DDS switching service)
        missing = by_status[ReconcileStatus.MISSING_IN_DDS]
        assert missing.subscription_id == "s-c" and missing.switching_service_id is None

    def test_both_sources_failed_yields_error_no_rows(self):
        result = reconcile_stps(None, None)
        assert result.error is not None and result.rows == []

    @pytest.mark.parametrize(
        ("wfo", "dds", "expected_statuses"),
        [
            pytest.param(None, [], [], id="wfo-failed-dds-empty"),
            pytest.param([], None, [], id="dds-failed-wfo-empty"),
            pytest.param(None, [DdsStp(stp_id="dom:portA")], [ReconcileStatus.DDS_ONLY], id="wfo-failed-dds-side"),
            pytest.param(
                [StpSub(subscription_id="s-a", stp_id="urn:ogf:network:dom:portA")],
                None,
                [ReconcileStatus.MISSING_IN_DDS],
                id="dds-failed-wfo-side",
            ),
        ],
    )
    def test_single_source_failure_degrades_to_available_side(self, wfo, dds, expected_statuses):
        result = reconcile_stps(wfo, dds)
        assert result.error is None and [row.status for row in result.rows] == expected_statuses


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
            DdsSdp(stp_a_id="dom:portB?vlan=100", stp_z_id="dom:portA?vlan=200", description="dds A-B"),
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

    def test_both_sources_failed_yields_error_no_rows(self):
        result = reconcile_sdps(None, None)
        assert result.error is not None and result.rows == []

    @pytest.mark.parametrize(
        ("wfo", "dds", "expected_statuses"),
        [
            pytest.param(None, [], [], id="wfo-failed-dds-empty"),
            pytest.param([], None, [], id="dds-failed-wfo-empty"),
            pytest.param(
                None,
                [DdsSdp(stp_a_id="dom:portA", stp_z_id="dom:portB")],
                [ReconcileStatus.DDS_ONLY],
                id="wfo-failed-dds-side",
            ),
            pytest.param(
                [
                    SdpSub(
                        subscription_id="sdp-1",
                        stps=[SdpMember(stp_id="dom:portA"), SdpMember(stp_id="dom:portB")],
                    )
                ],
                None,
                [ReconcileStatus.MISSING_IN_DDS],
                id="dds-failed-wfo-side",
            ),
        ],
    )
    def test_single_source_failure_degrades_to_available_side(self, wfo, dds, expected_statuses):
        result = reconcile_sdps(wfo, dds)
        assert result.error is None and [row.status for row in result.rows] == expected_statuses
