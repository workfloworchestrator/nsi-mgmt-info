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

from contextlib import ExitStack
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from amiss import app
from amiss.frontend.circuits import _in_tab
from amiss.frontend.home import Tone, _stat_line
from amiss.sources.aggregator import CircuitOnSdp, PathSegment, SpectrumRow, SpectrumView
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


def _patch_dashboard_sources(circuits=None, stps=None, sdps=None, spectrum=None):
    """Patch the dashboard's live sources so the landing page renders without network calls."""
    return (
        patch("amiss.frontend.home.get_circuits", return_value=circuits if circuits is not None else []),
        patch("amiss.frontend.home.get_stps", return_value=stps or StpReconciliation(rows=[])),
        patch("amiss.frontend.home.get_sdps", return_value=sdps or SdpReconciliation(rows=[])),
        patch("amiss.frontend.home.get_spectrum", return_value=spectrum or SpectrumView(rows=[])),
    )


def test_landing_page_injects_brand_style():
    # "/" is the SPA HTML shell (catch-all), where the brand <style> is injected; it does not call home().
    response = client.get("/")
    assert response.status_code == 200
    assert "#2a5c5c" in response.text  # brand navbar colour injected before </body>


def test_dashboard_shows_summary_cards():
    circuits = [CircuitRow(subscription_id="a", state="ACTIVATED"), CircuitRow(subscription_id="b", state="FAILED")]
    stps = StpReconciliation(rows=[StpRow(stp_id="x", status=ReconcileStatus.IN_BOTH)])
    spectrum = SpectrumView(
        rows=[SpectrumRow(subscription_id="d1", sdp_name="A<->B", stp_a="a", stp_z="b", circuit_count=1)]
    )
    with ExitStack() as stack:
        for p in _patch_dashboard_sources(circuits=circuits, stps=stps, spectrum=spectrum):
            stack.enter_context(p)
        response = client.get("/api/")  # the dashboard component tree (the SPA fetches this)
    assert response.status_code == 200
    # circuit card with state breakdown, reconciliation card, and the spectrum counts card
    assert "Circuits" in response.text and "Activated" in response.text
    assert "Termination Points" in response.text and "backed by DDS" in response.text
    assert "Spectrum" in response.text and "SDPs in use" in response.text


def test_dashboard_card_shows_unavailable_on_source_failure():
    with ExitStack() as stack:
        for p in _patch_dashboard_sources(stps=StpReconciliation(error="STP source down")):
            stack.enter_context(p)
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


@pytest.mark.parametrize("path", ["/api/circuits/terminated", "/api/circuits/all"], ids=["terminated", "all"])
def test_circuit_tab_routes_render(path):
    with patch(
        "amiss.frontend.circuits.get_circuits", return_value=[CircuitRow(subscription_id="x", state="TERMINATED")]
    ):
        assert client.get(path).status_code == 200


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


def test_circuit_detail_shows_path_segments():
    rows = [CircuitRow(subscription_id="sub-1", description="c", connection_id="conn-1")]
    segments = [
        PathSegment(order=0, provider_nsa="nsa-a", source_stp="a", dest_stp="b", capacity=1000, status="ACTIVATED")
    ]
    with (
        patch("amiss.frontend.circuits.get_circuits", return_value=rows),
        patch("amiss.frontend.circuits.get_circuit_path", return_value=segments),
    ):
        response = client.get("/api/circuits/sub-1/")
    assert response.status_code == 200
    assert "Path" in response.text and "nsa-a" in response.text


def test_circuit_detail_path_unavailable():
    rows = [CircuitRow(subscription_id="sub-1", connection_id="conn-1")]
    with (
        patch("amiss.frontend.circuits.get_circuits", return_value=rows),
        patch("amiss.frontend.circuits.get_circuit_path", return_value=None),
    ):
        response = client.get("/api/circuits/sub-1/")
    assert response.status_code == 200
    assert "Path unavailable" in response.text


def test_circuit_detail_not_found():
    with patch("amiss.frontend.circuits.get_circuits", return_value=[]):
        response = client.get("/api/circuits/does-not-exist/")
    assert response.status_code == 200
    assert "No circuit with id" in response.text


def test_dashboard_circuit_card_unavailable_when_wfo_unreachable():
    with (
        patch("amiss.frontend.home.get_circuits", return_value=None),
        patch("amiss.frontend.home.get_stps", return_value=StpReconciliation(rows=[])),
        patch("amiss.frontend.home.get_sdps", return_value=SdpReconciliation(rows=[])),
        patch("amiss.frontend.home.get_spectrum", return_value=SpectrumView(rows=[])),
    ):
        response = client.get("/api/")
    assert response.status_code == 200
    assert "unavailable" in response.text


_SDP = SpectrumRow(
    subscription_id="d1",
    sdp_name="A<->B",
    stp_a="dom:portA",
    stp_z="dom:portB",
    circuit_count=1,
    total_capacity=1000,
    circuits=[
        CircuitOnSdp(
            subscription_id="sub-1",
            description="AMS-NYC",
            connection_id="conn-1",
            vlan="100",
            capacity=1000,
            status="ACTIVATED",
        )
    ],
)


def test_spectrum_page_renders():
    with patch("amiss.frontend.spectrum.get_spectrum", return_value=SpectrumView(rows=[_SDP])):
        response = client.get("/api/spectrum")
    assert response.status_code == 200
    assert "A<->B" in response.text and "dom:portA" in response.text


def test_spectrum_detail_shows_circuits_on_sdp():
    with patch("amiss.frontend.spectrum.get_spectrum", return_value=SpectrumView(rows=[_SDP])):
        response = client.get("/api/spectrum/d1/")
    assert response.status_code == 200
    assert "AMS-NYC" in response.text and "conn-1" in response.text
    # cross-link to the circuit detail (FastUI stores the per-row URL template)
    assert "/circuits/{subscription_id}/" in response.text


def test_spectrum_detail_not_found():
    with patch("amiss.frontend.spectrum.get_spectrum", return_value=SpectrumView(rows=[])):
        response = client.get("/api/spectrum/nope/")
    assert response.status_code == 200
    assert "No SDP with id" in response.text


def test_spectrum_page_shows_error_when_unreachable():
    with patch("amiss.frontend.spectrum.get_spectrum", return_value=SpectrumView(error="down")):
        response = client.get("/api/spectrum")
    assert response.status_code == 200
    assert "unavailable" in response.text.lower()


@pytest.mark.parametrize(
    ("target", "result", "path", "expected"),
    [
        pytest.param(
            "amiss.frontend.stp.get_stps",
            StpReconciliation(rows=[StpRow(stp_id="dom:portA", status=ReconcileStatus.IN_BOTH)]),
            "/api/stp",
            "dom:portA",
            id="stp",
        ),
        pytest.param(
            "amiss.frontend.sdp.get_sdps",
            SdpReconciliation(
                rows=[SdpRow(stp_a_id="dom:portA", stp_z_id="dom:portB", status=ReconcileStatus.DDS_ONLY)]
            ),
            "/api/sdp",
            "dom:portA",
            id="sdp",
        ),
    ],
)
def test_reconciliation_page_renders(target, result, path, expected):
    with patch(target, return_value=result):
        response = client.get(path)
    assert response.status_code == 200 and expected in response.text


@pytest.mark.parametrize(
    ("target", "reconciliation", "path"),
    [
        pytest.param("amiss.frontend.stp.get_stps", StpReconciliation(error="STP source down"), "/api/stp", id="stp"),
        pytest.param("amiss.frontend.sdp.get_sdps", SdpReconciliation(error="SDP source down"), "/api/sdp", id="sdp"),
    ],
)
def test_reconciliation_page_shows_error(target, reconciliation, path):
    with patch(target, return_value=reconciliation):
        response = client.get(path)
    assert response.status_code == 200 and reconciliation.error in response.text
