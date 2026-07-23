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

"""Tests for amiss.sources.dds_topology: DDS proxy JSON -> reconciliation DTOs (mocked HTTP)."""

import json
from unittest.mock import patch

import pytest

from amiss.sources import dds_topology

STP_JSON = json.dumps(
    [
        {
            "id": "urn:ogf:network:dom:portA",
            "labelGroup": "1-10",
            "name": "Port A",
            "switchingServiceId": "urn:ogf:network:dom:switch:EVTS.ANA",
        },
        {"id": "urn:ogf:network:dom:portB", "labelGroup": "1-20", "name": "no switching service"},
        {"labelGroup": "1-20", "name": "no id here"},  # malformed: skipped
    ]
).encode()

SDP_JSON = json.dumps(
    [
        {"stpAId": "urn:ogf:network:dom:portA", "stpZId": "urn:ogf:network:dom:portB"},
        {"stpAId": "urn:ogf:network:dom:only-a"},  # incomplete pair: skipped
    ]
).encode()


def test_fetch_dds_stps_parses_and_skips_malformed():
    with patch.object(dds_topology, "get_dds_proxy_stps", return_value=STP_JSON):
        stps = dds_topology.fetch_dds_stps()
    assert [s.stp_id for s in stps] == ["dom:portA", "dom:portB"]
    assert stps[0].vlan_range == "1-10" and stps[0].description == "Port A"
    # switchingServiceId is mapped with the URN prefix stripped; absent -> None
    assert stps[0].switching_service_id == "dom:switch:EVTS.ANA"
    assert stps[1].switching_service_id is None


def test_fetch_dds_sdps_parses_and_skips_incomplete():
    with patch.object(dds_topology, "get_dds_proxy_sdps", return_value=SDP_JSON):
        sdps = dds_topology.fetch_dds_sdps()
    assert len(sdps) == 1
    assert sdps[0].stp_a_id == "dom:portA" and sdps[0].stp_z_id == "dom:portB"


@pytest.mark.parametrize("raw", [None, b"<html>", b"{}"], ids=["fetch-failed", "bad-json", "not-a-list"])
def test_fetch_dds_stps_none_on_failure(raw):
    with patch.object(dds_topology, "get_dds_proxy_stps", return_value=raw):
        assert dds_topology.fetch_dds_stps() is None


@pytest.mark.parametrize("raw", [None, b"<html>", b"{}"], ids=["fetch-failed", "bad-json", "not-a-list"])
def test_fetch_dds_sdps_none_on_failure(raw):
    with patch.object(dds_topology, "get_dds_proxy_sdps", return_value=raw):
        assert dds_topology.fetch_dds_sdps() is None
