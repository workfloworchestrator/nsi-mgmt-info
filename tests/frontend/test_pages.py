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

import pytest
from fastapi.testclient import TestClient

from amiss import app
from amiss.frontend.circuits import _in_tab
from amiss.frontend.home import Tone, _stat_line
from amiss.sources.reconcile import ReconcileStatus, SdpReconciliation, SdpRow, StpReconciliation, StpRow
from amiss.sources.wfo import CircuitRow

client = TestClient(app)


@pytest.mark.parametrize(
    ("tone", "count", "expected_class"),
    [
        pytest.param(Tone.GOOD, 5, "text-success", id="good-green"),
        pytest.param(Tone.BAD, 3, "text-danger", id="bad-present-red"),
        pytest.param(Tone.BAD, 0, "text-muted", id="bad-zero-muted"),
        pytest.param(Tone.NEUTRAL, 9, "text-muted", id="neutral-muted"),
    ],
)
def test_stat_line_tone_colour(tone, count, expected_class):
    assert expected_class in _stat_line("Label", count, tone).class_name


@pytest.mark.parametrize(
    ("state", "tab", "expected"),
    [
        pytest.param("ACTIVATED", "activated", True, id="activated-in-activated"),
        pytest.param("FAILED", "activated", False, id="failed-not-in-activated"),
        pytest.param("TERMINATED", "activated", False, id="terminated-not-in-activated"),
        pytest.param(None, "activated", True, id="null-state-in-activated"),
        pytest.param("FAILED", "failed", True, id="failed-in-failed"),
        pytest.param("failed", "failed", True, id="failed-case-insensitive"),
        pytest.param("ACTIVATED", "failed", False, id="activated-not-in-failed"),
        pytest.param("TERMINATED", "terminated", True, id="terminated-in-terminated"),
        pytest.param("FAILED", "all", True, id="failed-in-all"),
        pytest.param("ACTIVATED", "all", True, id="activated-in-all"),
    ],
)
def test_in_tab(state, tab, expected):
    assert _in_tab(CircuitRow(subscription_id="x", state=state), tab) is expected


def _patch_dashboard_sources(circuits=None, stps=None, sdps=None):
    """Patch the dashboard's live sources so the landing page renders without network calls."""
    return (
        patch("amiss.frontend.home.get_circuits", return_value=circuits if circuits is not None else []),
        patch("amiss.frontend.home.get_stps", return_value=stps or StpReconciliation(rows=[])),
        patch("amiss.frontend.home.get_sdps", return_value=sdps or SdpReconciliation(rows=[])),
    )


def test_landing_page_injects_brand_style():
    # "/" is the SPA HTML shell (catch-all), where the brand <style> is injected; it does not call home().
    response = client.get("/")
    assert response.status_code == 200
    assert "#2a5c5c" in response.text  # brand navbar colour injected before </body>


def test_dashboard_shows_summary_cards():
    circuits = [CircuitRow(subscription_id="a", state="ACTIVATED"), CircuitRow(subscription_id="b", state="FAILED")]
    stps = StpReconciliation(rows=[StpRow(stp_id="x", status=ReconcileStatus.IN_BOTH)])
    p_circuits, p_stps, p_sdps = _patch_dashboard_sources(circuits=circuits, stps=stps)
    with p_circuits, p_stps, p_sdps:
        response = client.get("/api/")  # the dashboard component tree (the SPA fetches this)
    assert response.status_code == 200
    # circuit card with state breakdown, reconciliation card, and the spectrum link card
    assert "Circuits" in response.text and "Activated" in response.text
    assert "Termination Points" in response.text and "backed by DDS" in response.text
    assert "Spectrum" in response.text


def test_dashboard_card_shows_unavailable_on_source_failure():
    p_circuits, p_stps, p_sdps = _patch_dashboard_sources(stps=StpReconciliation(error="STP source down"))
    with p_circuits, p_stps, p_sdps:
        response = client.get("/api/")
    assert response.status_code == 200
    assert "unavailable" in response.text


def test_footer_logo_src_points_at_an_existing_file():
    from pathlib import Path

    from amiss.frontend.util import amiss_logo

    name = amiss_logo().components[0].src.rsplit("/", 1)[-1]
    # case-sensitive membership so a wrong-case ref (works on macOS, 404s on Linux) fails locally too
    assert name in {entry.name for entry in Path("static").iterdir()}


def test_circuits_page_renders():
    rows = [CircuitRow(subscription_id="sub-1", description="c", state="ACTIVATED", created_by="alice")]
    with patch("amiss.frontend.circuits.get_circuits", return_value=rows):
        response = client.get("/api/circuits")
    assert response.status_code == 200
    assert "sub-1" in response.text and "alice" in response.text


def test_circuits_failed_tab_filters_by_state():
    rows = [
        CircuitRow(subscription_id="ok", state="ACTIVATED"),
        CircuitRow(subscription_id="bad", state="FAILED"),
    ]
    with patch("amiss.frontend.circuits.get_circuits", return_value=rows):
        response = client.get("/api/circuits/failed")
    assert response.status_code == 200
    assert "bad" in response.text and "ok" not in response.text


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
