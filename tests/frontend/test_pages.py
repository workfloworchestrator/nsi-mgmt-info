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

"""Render tests for the circuits/STP/SDP pages: FastUI must serialize the DTO tables (mocked data)."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from amiss import app
from amiss.sources.reconcile import ReconcileStatus, SdpReconciliation, SdpRow, StpReconciliation, StpRow
from amiss.sources.wfo import CircuitRow

client = TestClient(app)


def test_circuits_page_renders():
    rows = [CircuitRow(subscription_id="sub-1", description="c", state="ACTIVE", created_by="alice")]
    with patch("amiss.frontend.circuits.get_circuits", return_value=rows):
        response = client.get("/api/circuits")
    assert response.status_code == 200
    assert "sub-1" in response.text and "alice" in response.text


def test_circuits_page_shows_error_when_unreachable():
    with patch("amiss.frontend.circuits.get_circuits", return_value=None):
        response = client.get("/api/circuits")
    assert response.status_code == 200
    assert "unavailable" in response.text.lower()


def test_circuit_detail_renders():
    rows = [CircuitRow(subscription_id="sub-1", description="circuit one")]
    with patch("amiss.frontend.circuits.get_circuits", return_value=rows):
        response = client.get("/api/circuits/sub-1/")
    assert response.status_code == 200
    assert "circuit one" in response.text


def test_stp_page_renders_reconciliation():
    result = StpReconciliation(rows=[StpRow(stp_id="dom:portA", status=ReconcileStatus.IN_BOTH)])
    with patch("amiss.frontend.stp.get_stps", return_value=result):
        response = client.get("/api/stp")
    assert response.status_code == 200
    assert "dom:portA" in response.text


def test_stp_page_shows_error():
    with patch("amiss.frontend.stp.get_stps", return_value=StpReconciliation(error="STP source down")):
        response = client.get("/api/stp")
    assert response.status_code == 200
    assert "STP source down" in response.text


def test_sdp_page_renders_reconciliation():
    result = SdpReconciliation(
        rows=[SdpRow(stp_a_id="dom:portA", stp_z_id="dom:portB", status=ReconcileStatus.DDS_ONLY)]
    )
    with patch("amiss.frontend.sdp.get_sdps", return_value=result):
        response = client.get("/api/sdp")
    assert response.status_code == 200
    assert "dom:portA" in response.text
