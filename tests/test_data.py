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

from amiss import data
from amiss.sources.reconcile import DdsSdp, DdsStp, ReconcileStatus
from amiss.sources.wfo import CircuitRow, SdpMember, SdpSub, StpSub


def test_get_circuits_passthrough():
    rows = [CircuitRow(subscription_id="c1")]
    with patch.object(data, "fetch_circuits", return_value=rows):
        assert data.get_circuits("tok") == rows


def test_get_circuits_none_on_failure():
    with patch.object(data, "fetch_circuits", return_value=None):
        assert data.get_circuits("tok") is None


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
