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
from amiss.data import NOT_AUTHORIZED, CircuitDetail, CircuitList, StpDetail
from amiss.frontend.circuits import _in_tab
from amiss.frontend.home import Tone, _stat_line
from amiss.settings import settings
from amiss.sources.aggregator import UNATTRIBUTED_ID, CircuitOnSdp, PathSegment, SpectrumRow, SpectrumView
from amiss.sources.providers import ProviderDetail, ProviderList, ProviderReservationRow, ProviderRow
from amiss.sources.reconcile import (
    DdsStp,
    NamedReconciliation,
    NamedRow,
    ReconcileStatus,
    SdpReconciliation,
    SdpRow,
    StpReconciliation,
    StpRow,
)
from amiss.sources.wfo import CircuitRow, StpSub, ValidationFailureRow, WfoUnauthorizedError
from tests.fastui_tree import texts as _texts
from tests.fastui_tree import walk as _walk

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
        pytest.param("RESERVED", "reserved", True, id="reserved-in-reserved"),
        pytest.param("reserved", "reserved", True, id="reserved-case-insensitive"),
        pytest.param("ACTIVATED", "reserved", False, id="activated-not-in-reserved"),
        pytest.param("TERMINATED", "terminated", True, id="terminated-in-terminated"),
        pytest.param("FAILED", "all", True, id="failed-in-all"),
        pytest.param("RESERVED", "all", True, id="reserved-in-all"),
        pytest.param("ACTIVATED", "all", True, id="activated-in-all"),
    ],
)
def test_in_tab(state, tab, expected):
    assert _in_tab(CircuitRow(subscription_id="x", state=state), tab) is expected


# The dashboard fetches each upstream directly (composing the cards itself), so tests stub the fetch
# functions on the home module. Default each to an empty list; override per test.
# Only the WFO legs forward the caller's token and so can raise WfoUnauthorizedError; the 401 test
# below is parametrized over exactly these, derived rather than mirrored so the two cannot drift.
_WFO_FETCHES = (
    "fetch_circuits",
    "fetch_topology_subscriptions",
    "fetch_switching_service_subscriptions",
    "fetch_stp_subscriptions",
    "fetch_sdp_subscriptions",
    "fetch_validation_failures",
)
_LOCAL_FETCHES = (
    "fetch_dds_topologies",
    "fetch_dds_switching_services",
    "fetch_dds_stps",
    "fetch_dds_sdps",
    "fetch_agg_circuits",
)
_DASHBOARD_FETCHES = _WFO_FETCHES + _LOCAL_FETCHES


def _dashboard_patches(**overrides):
    """Patch each dashboard fetch on amiss.frontend.home; overrides set specific return values."""
    values: dict = {name: [] for name in _DASHBOARD_FETCHES}
    values.update(overrides)
    return [patch(f"amiss.frontend.home.{name}", return_value=value) for name, value in values.items()]


def test_landing_page_injects_brand_style():
    # "/" is the SPA HTML shell (catch-all), where the brand <style> is injected; it does not call home().
    response = client.get("/")
    assert response.status_code == 200
    assert "#2a5c5c" in response.text  # brand navbar colour injected before </body>


def test_dashboard_shows_summary_cards():
    with ExitStack() as stack:
        for p in _dashboard_patches(
            fetch_circuits=[
                CircuitRow(subscription_id="a", state="ACTIVATED"),
                CircuitRow(subscription_id="b", state="FAILED"),
            ],
            fetch_stp_subscriptions=[StpSub(subscription_id="s", stp_id="urn:ogf:network:x")],
            fetch_dds_stps=[DdsStp(stp_id="x")],  # matches the STP sub -> "backed by DDS"
        ):
            stack.enter_context(p)
        response = client.get("/api/")  # the dashboard component tree (the SPA fetches this)
    assert response.status_code == 200
    # circuit card with state breakdown, reconciliation card, and the spectrum counts card
    assert "Circuits" in response.text and "Activated" in response.text
    assert "Termination Points" in response.text and "backed by DDS" in response.text
    assert "Spectrum" in response.text and "SDPs in use" in response.text


def _circuit_card_headline(cards) -> str | None:
    """Return the big number on the Circuits card: the sibling of its 'Circuits' heading."""
    card = next(
        (
            n
            for n in _walk(cards)
            if any(c.get("text") == "Circuits" and c.get("type") == "Heading" for c in n.get("components", []))
        ),
        None,
    )
    headline = next((c for c in (card or {}).get("components", []) if "display-6" in (c.get("className") or "")), None)
    return next((t.get("text") for t in (headline or {}).get("components", [])), None)


def test_dashboard_circuit_headline_excludes_terminated():
    """The headline counts Activated, Failed and Reserved; Terminated is left out."""
    circuits = [
        CircuitRow(subscription_id="a", state="ACTIVATED"),
        CircuitRow(subscription_id="b", state="FAILED"),
        CircuitRow(subscription_id="c", state="TERMINATED"),
        CircuitRow(subscription_id="d", state="TERMINATED"),
        CircuitRow(subscription_id="e", state="RESERVED"),
        CircuitRow(subscription_id="f", state="RESERVED"),
    ]
    with ExitStack() as stack:
        for p in _dashboard_patches(fetch_circuits=circuits):
            stack.enter_context(p)
        cards = client.get("/api/").json()
    headline = _circuit_card_headline(cards)
    assert headline == "4", f"expected 4 of 6 (two terminated excluded), got {headline}"


def test_dashboard_fetches_each_source_once():
    # locks in the no-duplicate-fetch behaviour: each upstream is hit exactly once per dashboard load
    with ExitStack() as stack:
        mocks = {name: stack.enter_context(p) for name, p in zip(_DASHBOARD_FETCHES, _dashboard_patches())}
        response = client.get("/api/")
    assert response.status_code == 200
    assert all(mock.call_count == 1 for mock in mocks.values()), {n: m.call_count for n, m in mocks.items()}


def test_dashboard_card_shows_unavailable_on_source_failure():
    # a failed fetch (None) makes its card unavailable: reconcile_stps(None, ...) -> error state
    with ExitStack() as stack:
        for p in _dashboard_patches(fetch_stp_subscriptions=None):
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
    with patch("amiss.frontend.circuits.get_circuits", return_value=CircuitList(rows=rows)):
        response = client.get("/api/circuits")
    assert response.status_code == 200
    assert "sub-1" in response.text and "alice" in response.text


def test_circuits_failed_tab_filters_by_state():
    rows = [
        CircuitRow(subscription_id="ok", state="ACTIVATED"),
        CircuitRow(subscription_id="bad", state="FAILED"),
    ]
    with patch("amiss.frontend.circuits.get_circuits", return_value=CircuitList(rows=rows)):
        response = client.get("/api/circuits/failed")
    assert response.status_code == 200
    assert "bad" in response.text and "ok" not in response.text


def test_circuits_reserved_tab_filters_by_state():
    rows = [
        CircuitRow(subscription_id="ok", state="ACTIVATED"),
        CircuitRow(subscription_id="hold", state="RESERVED"),
    ]
    with patch("amiss.frontend.circuits.get_circuits", return_value=CircuitList(rows=rows)):
        response = client.get("/api/circuits/reserved")
    assert response.status_code == 200
    assert "hold" in response.text and "ok" not in response.text


@pytest.mark.parametrize(
    "path",
    ["/api/circuits/reserved", "/api/circuits/terminated", "/api/circuits/all"],
    ids=["reserved", "terminated", "all"],
)
def test_circuit_tab_routes_render(path):
    with patch(
        "amiss.frontend.circuits.get_circuits",
        return_value=CircuitList(rows=[CircuitRow(subscription_id="x", state="TERMINATED")]),
    ):
        assert client.get(path).status_code == 200


def test_circuits_list_renders_the_reason_it_has_no_data():
    with patch("amiss.frontend.circuits.get_circuits", return_value=CircuitList(error="refused")):
        response = client.get("/api/circuits")
    assert response.status_code == 200
    assert "refused" in response.text


_CIRCUIT_DETAIL = "amiss.frontend.circuits.get_circuit_detail"


def _circuit(**fields) -> CircuitDetail:
    """A circuit detail for sub-1 with no path and no SDPs; ``path``/``sdps`` override those, the rest go to the row."""
    sections = {"path": [], "sdps": []} | {key: fields.pop(key) for key in ("path", "sdps") if key in fields}
    return CircuitDetail(circuit=CircuitRow(subscription_id="sub-1", **fields), **sections)


def test_circuit_list_links_the_endpoints_to_their_stps():
    rows = [CircuitRow(subscription_id="sub-1", source="Port A", source_stp_subscription_id="stp-a")]
    with patch("amiss.frontend.circuits.get_circuits", return_value=CircuitList(rows=rows)):
        response = client.get("/api/circuits")
    assert "/stp/{source_stp_subscription_id}/" in response.text and "/stp/{dest_stp_subscription_id}/" in response.text


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        pytest.param(_circuit(description="circuit one"), "Circuit circuit one", id="renders"),
        pytest.param(CircuitDetail(error="refused"), "refused", id="error"),
        pytest.param(CircuitDetail(), "No circuit with id sub-1.", id="not-found"),
        pytest.param(
            _circuit(path=None), "Path unavailable: the aggregator proxy could not be reached.", id="path-unavailable"
        ),
        pytest.param(_circuit(), "_No path segments reported for this circuit._", id="no-path"),
        pytest.param(
            _circuit(sdps=None),
            "SDPs unavailable: the aggregator proxy or WFO could not be reached.",
            id="sdps-unavailable",
        ),
        pytest.param(_circuit(), "_This circuit crosses no known SDP._", id="no-sdps"),
    ],
)
def test_circuit_detail_says_what_it_has(detail, expected):
    with patch(_CIRCUIT_DETAIL, return_value=detail):
        response = client.get("/api/circuits/sub-1/")
    assert response.status_code == 200
    assert expected in _texts(response.json())


def test_circuit_detail_links_path_stps_and_the_sdps_crossed():
    detail = _circuit(
        path=[PathSegment(order=0, provider_nsa="nsa-a", source_stp="a", source_stp_subscription_id="stp-a")],
        sdps=[_SDP],
        source_stp="Port A",
        source_stp_subscription_id="stp-a",
    )
    with patch(_CIRCUIT_DETAIL, return_value=detail):
        response = client.get("/api/circuits/sub-1/")
    page = response.text
    assert "nsa-a" in page and "A<->B" in page
    assert "/stp/{source_stp_subscription_id}/" in page and "/sdp/{subscription_id}/" in page
    # the owner ids only serve as link targets, so the details list does not show them as fields
    assert '"field":"source_stp_subscription_id"' not in page.replace(" ", "")


@pytest.mark.parametrize(
    ("state", "last_error", "banner"),
    [
        pytest.param("FAILED", "activateFailed: socket", True, id="failed-with-error"),
        pytest.param("FAILED", None, False, id="failed-without-error"),
        pytest.param("ACTIVATED", "activateFailed: socket", False, id="recovered-keeps-field-only"),
    ],
)
def test_circuit_detail_last_error(state, last_error, banner):
    with patch(_CIRCUIT_DETAIL, return_value=_circuit(state=state, last_error=last_error)):
        page = client.get("/api/circuits/sub-1/").json()
    alerts = [node for node in _walk(page) if "alert-danger" in str(node.get("className", ""))]
    assert bool(alerts) is banner
    assert last_error in _texts(alerts[0]) if banner else not alerts
    assert "last_error" in str(page)  # the field is always in the details list


def test_dashboard_circuit_card_unavailable_when_wfo_unreachable():
    with ExitStack() as stack:
        for p in _dashboard_patches(fetch_circuits=None):
            stack.enter_context(p)
        response = client.get("/api/")
    assert response.status_code == 200
    assert "unavailable" in response.text


def test_dashboard_says_not_authorized_rather_than_unavailable():
    """The dashboard is where a blocked user lands first, so it must not read as an outage."""
    with ExitStack() as stack:
        for p in _dashboard_patches():
            stack.enter_context(p)
        stack.enter_context(patch("amiss.frontend.home.fetch_circuits", side_effect=WfoUnauthorizedError))
        response = client.get("/api/")
    assert response.status_code == 200
    assert NOT_AUTHORIZED in response.text


_CIRCUIT_ON_SDP = CircuitOnSdp(
    subscription_id="sub-1",
    description="AMS-NYC",
    connection_id="conn-1",
    vlan="100",
    bandwidth=1000,
    status="ACTIVATED",
)

_SDP = SpectrumRow(
    subscription_id="d1",
    sdp_name="A<->B",
    stp_a="dom:portA",
    stp_z="dom:portB",
    circuit_count=1,
    sdp_capacity=4000,
    total_capacity=1000,
    circuits=[_CIRCUIT_ON_SDP],
)

_UNATTRIBUTED = SpectrumRow(
    subscription_id=UNATTRIBUTED_ID,
    sdp_name="Unattributed circuits",
    circuit_count=1,
    total_capacity=1000,
    circuits=[CircuitOnSdp(subscription_id="sub-9", description="ORPHAN", bandwidth=1000)],
)


def test_spectrum_page_renders():
    with patch("amiss.frontend.spectrum.get_spectrum", return_value=SpectrumView(rows=[_SDP])):
        response = client.get("/api/spectrum")
    assert response.status_code == 200
    assert "A<->B" in response.text and "dom:portA" in response.text
    # the SDP links to its own page, not to a spectrum-only drill-in
    assert "/sdp/{subscription_id}/" in response.text


def test_spectrum_page_shows_utilisation():
    with patch("amiss.frontend.spectrum.get_spectrum", return_value=SpectrumView(rows=[_SDP])):
        response = client.get("/api/spectrum")
    assert '"utilisation":25' in response.text.replace(" ", "")


def test_spectrum_page_lists_unattributed_circuits_inline():
    """The unattributed bucket has no SDP subscription, so /spectrum shows it rather than linking away."""
    with patch("amiss.frontend.spectrum.get_spectrum", return_value=SpectrumView(rows=[_SDP, _UNATTRIBUTED])):
        response = client.get("/api/spectrum")
    assert response.status_code == 200
    assert "Unattributed circuits" in response.text and "ORPHAN" in response.text


def test_spectrum_page_shows_the_reason_it_has_no_data():
    with patch("amiss.frontend.spectrum.get_spectrum", return_value=SpectrumView(error="down")):
        response = client.get("/api/spectrum")
    assert response.status_code == 200
    assert "down" in response.text


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


_STP_ROWS = [
    StpRow(subscription_id="stp-1", stp_id="dom:portA", capacity=100000, status=ReconcileStatus.IN_BOTH),
    StpRow(stp_id="dom:portB", status=ReconcileStatus.DDS_ONLY),
    StpRow(subscription_id="stp-3", stp_id="dom:portC", status=ReconcileStatus.MISSING_IN_DDS),
]

_SDP_ROWS = [
    SdpRow(subscription_id="sdp-1", stp_a_id="dom:portA", stp_z_id="other:portZ", status=ReconcileStatus.IN_BOTH),
    SdpRow(stp_a_id="dom:portB", stp_z_id="other:portY", status=ReconcileStatus.DDS_ONLY),
]


def _stp_detail(**overrides) -> StpDetail:
    """An STP detail holding _STP_ROWS and no related rows; overrides replace a section."""
    sections = {"stps": StpReconciliation(rows=_STP_ROWS), "circuits": CircuitList(), "sdps": SdpReconciliation()}
    return StpDetail(**(sections | overrides))


_STP_DETAIL, _SDP_DETAIL = "amiss.frontend.stp.get_stp_detail", "amiss.frontend.sdp.get_sdp_detail"


_STPS, _SDPS = "amiss.frontend.stp.get_stps", "amiss.frontend.sdp.get_sdps"
_STP_RECONCILIATION = StpReconciliation(rows=_STP_ROWS)
_SDP_RECONCILIATION = SdpReconciliation(rows=_SDP_ROWS)


@pytest.mark.parametrize(
    ("target", "result", "path", "present", "absent"),
    [
        pytest.param(_STPS, _STP_RECONCILIATION, "/api/stp", "dom:portA", "no-such-port", id="stp-all"),
        pytest.param(_STPS, _STP_RECONCILIATION, "/api/stp/backed", "dom:portA", "dom:portB", id="stp-backed"),
        pytest.param(_STPS, _STP_RECONCILIATION, "/api/stp/dds-only", "dom:portB", "dom:portA", id="stp-dds-only"),
        pytest.param(_STPS, _STP_RECONCILIATION, "/api/stp/missing", "dom:portC", "dom:portA", id="stp-missing"),
        pytest.param(_SDPS, _SDP_RECONCILIATION, "/api/sdp", "other:portZ", "no-such-port", id="sdp-all"),
        pytest.param(_SDPS, _SDP_RECONCILIATION, "/api/sdp/dds-only", "dom:portB", "other:portZ", id="sdp-dds-only"),
    ],
)
def test_status_tabs_filter(target, result, path, present, absent):
    with patch(target, return_value=result):
        response = client.get(path)
    assert response.status_code == 200
    assert present in response.text and absent not in response.text


@pytest.mark.parametrize(
    ("target", "result", "path", "link"),
    [
        pytest.param(
            "amiss.frontend.stp.get_stps",
            StpReconciliation(rows=_STP_ROWS),
            "/api/stp",
            "/stp/{subscription_id}/",
            id="stp",
        ),
        pytest.param(
            "amiss.frontend.sdp.get_sdps",
            SdpReconciliation(rows=_SDP_ROWS),
            "/api/sdp",
            "/sdp/{subscription_id}/",
            id="sdp",
        ),
    ],
)
def test_reconciliation_list_links_the_short_id_to_the_detail_page(target, result, path, link):
    with patch(target, return_value=result):
        response = client.get(path)
    # the 8-char id is shown and carries the row's detail link; the full uuid is not in the table
    assert '"short_id"' in response.text and link in response.text


def test_stp_detail_lists_only_the_circuits_on_that_stp():
    """Matching is on the endpoint's STP id, and terminated circuits are left out.

    ``source_stp``/``dest_stp`` carry the STP's *name* whenever it has one (which is what the circuits
    table shows), so a match against those finds nothing on real data.
    """
    circuits = CircuitList(
        rows=[
            CircuitRow(
                subscription_id="c1",
                description="ON-PORT-A",
                state="ACTIVATED",
                source_stp="University of Amsterdam",
                source_stp_id="urn:ogf:network:dom:portA",
                dest_stp="Somewhere Else",
                dest_stp_id="dom:portZ",
            ),
            CircuitRow(
                subscription_id="c2",
                description="ELSEWHERE",
                state="ACTIVATED",
                source_stp="Other Port",
                source_stp_id="dom:portQ",
                dest_stp="Somewhere Else",
                dest_stp_id="dom:portZ",
            ),
            CircuitRow(
                subscription_id="c3",
                description="OLD-ON-PORT-A",
                state="TERMINATED",
                source_stp="University of Amsterdam",
                source_stp_id="urn:ogf:network:dom:portA",
                dest_stp="Somewhere Else",
                dest_stp_id="dom:portZ",
            ),
        ]
    )
    with patch(_STP_DETAIL, return_value=_stp_detail(circuits=circuits)):
        response = client.get("/api/stp/stp-1/")
    assert response.status_code == 200
    assert "ON-PORT-A" in response.text
    assert "ELSEWHERE" not in response.text  # different port
    assert "OLD-ON-PORT-A" not in response.text  # right port, but terminated


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        # a failed fetch must not read as 'no circuits use this port'
        pytest.param({"circuits": CircuitList(error="WFO down")}, "WFO down", id="circuits-unavailable"),
        pytest.param({"sdps": SdpReconciliation(error="SDP data unavailable")}, "SDP data unavailable", id="sdps-down"),
        pytest.param({}, "_This STP is not an end of any SDP._", id="no-sdps"),
    ],
)
def test_stp_detail_degrades_per_section(overrides, expected):
    with patch(_STP_DETAIL, return_value=_stp_detail(**overrides)):
        response = client.get("/api/stp/stp-1/")
    assert response.status_code == 200 and expected in _texts(response.json())


def test_stp_detail_lists_the_sdps_on_that_stp_and_links_the_provider():
    # stp-1 is dom:portA: sdp-1 has it as an end, the DDS-only SDP on dom:portB does not
    linked = [_STP_ROWS[0].model_copy(update={"provider_nsa": _SUPA, "provider_name": "SURF uPA"})]
    detail = _stp_detail(stps=StpReconciliation(rows=linked), sdps=SdpReconciliation(rows=_SDP_ROWS))
    with patch(_STP_DETAIL, return_value=detail):
        page = client.get("/api/stp/stp-1/").json()
    sdps = next(n for n in _walk(page) if n.get("type") == "Table")
    assert [row["subscription_id"] for row in sdps["data"]] == ["sdp-1"]
    details = next(n for n in _walk(page) if n.get("type") == "Details")
    assert details["data"]["provider_name"] == "SURF uPA"
    assert "/providers/{provider_nsa}/" in str(details["fields"])


def test_sdp_detail_shows_circuits_on_sdp():
    spectrum = SpectrumView(rows=[SpectrumRow(subscription_id="sdp-1", circuits=[_CIRCUIT_ON_SDP])])
    with patch("amiss.frontend.sdp.get_sdp_detail", return_value=(SdpReconciliation(rows=_SDP_ROWS), spectrum)):
        response = client.get("/api/sdp/sdp-1/")
    assert response.status_code == 200
    assert "AMS-NYC" in response.text
    # cross-link to the circuit detail (FastUI stores the per-row URL template)
    assert "/circuits/{subscription_id}/" in response.text


@pytest.mark.parametrize(
    ("target", "value", "path", "expected"),
    [
        pytest.param(
            _STP_DETAIL, _stp_detail(stps=StpReconciliation(rows=[])), "/api/stp/nope/", "nope", id="stp-not-found"
        ),
        pytest.param(
            _SDP_DETAIL, (SdpReconciliation(rows=[]), SpectrumView()), "/api/sdp/nope/", "nope", id="sdp-not-found"
        ),
        pytest.param(
            _STP_DETAIL,
            _stp_detail(stps=StpReconciliation(error="STP source down")),
            "/api/stp/stp-1/",
            "source down",
            id="stp-source-down",
        ),
        pytest.param(
            _SDP_DETAIL,
            (SdpReconciliation(error="SDP source down"), SpectrumView()),
            "/api/sdp/sdp-1/",
            "source down",
            id="sdp-source-down",
        ),
    ],
)
def test_detail_page_says_why_it_has_no_row(target, value, path, expected):
    with patch(target, return_value=value):
        response = client.get(path)
    assert response.status_code == 200 and expected in response.text


_FAILURE = ValidationFailureRow(
    process_id="p-1",
    workflow_name="validate_stp",
    last_status="inconsistent_data",
    started_at="2026-08-24 01:10:00",
    failed_reason="capacity drifted",
    subscription_id="0123456789ab",
    description="some STP",
)


def test_dashboard_shows_no_validation_failures_when_clean():
    with ExitStack() as stack:
        for p in _dashboard_patches(fetch_validation_failures=[]):
            stack.enter_context(p)
        page = client.get("/api/").json()
    assert "Validation failures: 0" in _texts(page)


def test_dashboard_lists_validation_failures():
    with ExitStack() as stack:
        for p in _dashboard_patches(fetch_validation_failures=[_FAILURE]):
            stack.enter_context(p)
        page = client.get("/api/").json()
    table = next((n for n in _walk(page) if n.get("type") == "Table"), None)
    assert table is not None, "expected a validation failure table"
    assert table["data"][0]["workflow_name"] == "validate_stp"
    assert table["data"][0]["short_id"] == "01234567"


def test_dashboard_warns_when_validation_status_unavailable():
    # a failed fetch is None, distinct from an empty list: say so rather than claim everything is fine
    with ExitStack() as stack:
        for p in _dashboard_patches(fetch_validation_failures=None):
            stack.enter_context(p)
        page = client.get("/api/").json()
    assert "Validation status unavailable." in _texts(page)


@pytest.mark.parametrize("refused", _WFO_FETCHES)
def test_dashboard_reports_not_authorized_whichever_wfo_fetch_is_refused(refused):
    """Every WFO future must be resolved inside home()'s guard; one resolved after it 500s on a 401."""
    with ExitStack() as stack:
        for name, p in zip(_DASHBOARD_FETCHES, _dashboard_patches()):
            mock = stack.enter_context(p)
            if name == refused:
                mock.side_effect = WfoUnauthorizedError
        response = client.get("/api/")
    assert response.status_code == 200
    assert NOT_AUTHORIZED in _texts(response.json())


@pytest.mark.parametrize(
    ("path", "accessor", "title"),
    [
        pytest.param("/api/topology", "get_topologies", "Topologies", id="topology"),
        pytest.param("/api/switching-service", "get_switching_services", "Switching Services", id="switching-service"),
    ],
)
class TestInventoryPages:
    """Topology and SwitchingService share one page definition, so both are driven through one suite."""

    def test_renders_rows(self, path, accessor, title):
        rows = [
            NamedRow(
                subscription_id="abcdef1234", object_id="dom:topo", description="A", status=ReconcileStatus.IN_BOTH
            ),
            NamedRow(object_id="peer:topo", description="Peer", status=ReconcileStatus.DDS_ONLY),
        ]
        with patch(f"amiss.data.{accessor}", return_value=NamedReconciliation(rows=rows)):
            page = client.get(path).json()
        table = next(n for n in _walk(page) if n.get("type") == "Table")
        assert [r["object_id"] for r in table["data"]] == ["dom:topo", "peer:topo"]
        assert title in _texts(page)

    def test_dds_only_tab_filters(self, path, accessor, title):
        rows = [
            NamedRow(subscription_id="s", object_id="dom:topo", status=ReconcileStatus.IN_BOTH),
            NamedRow(object_id="peer:topo", status=ReconcileStatus.DDS_ONLY),
        ]
        with patch(f"amiss.data.{accessor}", return_value=NamedReconciliation(rows=rows)):
            page = client.get(f"{path}/dds-only").json()
        table = next(n for n in _walk(page) if n.get("type") == "Table")
        assert [r["object_id"] for r in table["data"]] == ["peer:topo"]
        assert title in _texts(page)

    def test_shows_the_error_instead_of_an_empty_table(self, path, accessor, title):
        error = NamedReconciliation(error="Topology reconciliation unavailable: a source could not be reached")
        with patch(f"amiss.data.{accessor}", return_value=error):
            page = client.get(path).json()
        assert error.error in _texts(page)
        assert title in _texts(page)
        assert not any(n.get("type") == "Table" for n in _walk(page))


# --- Providers ----------------------------------------------------------------------------------------

_SUPA = "urn:ogf:network:surf.nl:2020:nsa:supa"
_PROVIDER = ProviderRow(nsa_id=_SUPA, name="SURF uPA", provider_url="https://supa/provider")
_RESERVATIONS = [
    ProviderReservationRow(
        connection_id="child-active",
        lifecycle_state="Created",
        subscription_id="sub-1",
        source_stp="port-a?vlan=1",
        source_stp_subscription_id="stp-a",
    ),
    ProviderReservationRow(connection_id="child-gone", lifecycle_state="Terminated"),
    ProviderReservationRow(connection_id="child-failed", lifecycle_state="Failed"),
]


def test_provider_list_links_the_name_to_the_detail_page():
    with patch("amiss.frontend.providers.get_providers", return_value=ProviderList(rows=[_PROVIDER])):
        response = client.get("/api/providers")
    assert response.status_code == 200
    assert "SURF uPA" in response.text and "/providers/{nsa_id}/" in response.text


def test_provider_list_error_banner():
    with patch("amiss.frontend.providers.get_providers", return_value=ProviderList(error="Providers unavailable")):
        page = client.get("/api/providers").json()
    assert "Providers unavailable" in _texts(page)
    assert not any(n.get("type") == "Table" for n in _walk(page))


@pytest.mark.parametrize(
    ("suffix", "shown", "hidden"),
    [
        pytest.param("", {"child-active"}, {"child-gone", "child-failed"}, id="active"),
        pytest.param("terminated", {"child-gone"}, {"child-active", "child-failed"}, id="terminated"),
        pytest.param("all", {"child-active", "child-gone", "child-failed"}, set(), id="all"),
    ],
)
def test_provider_detail_tabs(suffix, shown, hidden):
    detail = ProviderDetail(provider=_PROVIDER, reservations=_RESERVATIONS)
    with patch("amiss.frontend.providers.get_provider_detail", return_value=detail) as get:
        response = client.get(f"/api/providers/{_SUPA}/{suffix}")
    assert response.status_code == 200
    assert get.call_args.args[1] == _SUPA
    assert all(cid in response.text for cid in shown) and not any(cid in response.text for cid in hidden)


def test_provider_detail_unknown_tab_is_rejected():
    with patch("amiss.frontend.providers.get_provider_detail") as get:
        response = client.get(f"/api/providers/{_SUPA}/bogus")
    assert response.status_code == 422 and not get.called


def test_provider_detail_links_reservations_to_circuits_and_stps():
    detail = ProviderDetail(provider=_PROVIDER, reservations=_RESERVATIONS)
    with patch("amiss.frontend.providers.get_provider_detail", return_value=detail):
        response = client.get(f"/api/providers/{_SUPA}/")
    assert "/circuits/{subscription_id}/" in response.text
    assert "/stp/{source_stp_subscription_id}/" in response.text


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        pytest.param(ProviderDetail(), f"No provider with id {_SUPA}.", id="unknown-nsa"),
        pytest.param(ProviderDetail(error=NOT_AUTHORIZED), NOT_AUTHORIZED, id="not-authorized"),
        pytest.param(
            ProviderDetail(provider=_PROVIDER),
            "Reservations unavailable: the provider could not be reached.",
            id="upa-unreachable",
        ),
        pytest.param(ProviderDetail(provider=_PROVIDER, reservations=[]), "_No reservations in this tab._", id="none"),
    ],
)
def test_provider_detail_degrades(detail, expected):
    with patch("amiss.frontend.providers.get_provider_detail", return_value=detail):
        page = client.get(f"/api/providers/{_SUPA}/").json()
    assert expected in _texts(page)


def test_circuit_path_links_the_provider():
    detail = _circuit(path=[PathSegment(provider_nsa=_SUPA)])
    with patch(_CIRCUIT_DETAIL, return_value=detail):
        response = client.get("/api/circuits/sub-1/")
    assert "/providers/{provider_nsa}/" in response.text


# --- Navigation ---------------------------------------------------------------------------------------

_ORCHESTRATOR_UI = "https://orchestrator.example"


def _buttons(page) -> dict[str, dict]:
    """The detail page's buttons by text, mapped to their click event."""
    return {node["text"]: node["onClick"] for node in _walk(page) if node.get("type") == "Button"}


@pytest.mark.parametrize(
    ("target", "value", "path", "list_url", "orchestrator"),
    [
        pytest.param(_CIRCUIT_DETAIL, _circuit(), "/api/circuits/sub-1/", "/circuits", "sub-1", id="circuit"),
        pytest.param(_STP_DETAIL, _stp_detail(), "/api/stp/stp-1/", "/stp", "stp-1", id="stp"),
        pytest.param(
            _SDP_DETAIL,
            (SdpReconciliation(rows=_SDP_ROWS), SpectrumView()),
            "/api/sdp/sdp-1/",
            "/sdp",
            "sdp-1",
            id="sdp",
        ),
        pytest.param(
            "amiss.frontend.providers.get_provider_detail",
            ProviderDetail(provider=_PROVIDER, reservations=[]),
            f"/api/providers/{_SUPA}/",
            "/providers",
            None,
            id="provider-has-no-subscription",
        ),
    ],
)
def test_detail_page_buttons(monkeypatch, target, value, path, list_url, orchestrator):
    """Back follows the history, so it returns to the page that linked here; the list button is the fallback."""
    monkeypatch.setattr(settings, "NSI_AMISS_WFO_UI_URL", _ORCHESTRATOR_UI)
    with patch(target, return_value=value):
        buttons = _buttons(client.get(path).json())
    assert buttons.pop("Back") == {"type": "back"}
    assert next(event["url"] for text, event in buttons.items() if text.startswith("All ")) == list_url
    expected = {"type": "go-to", "url": f"{_ORCHESTRATOR_UI}/subscriptions/{orchestrator}", "target": "_blank"}
    assert buttons.get("Open in orchestrator") == (expected if orchestrator else None)


def test_no_orchestrator_button_without_a_ui_url(monkeypatch):
    monkeypatch.setattr(settings, "NSI_AMISS_WFO_UI_URL", None)
    with patch(_CIRCUIT_DETAIL, return_value=_circuit()):
        buttons = _buttons(client.get("/api/circuits/sub-1/").json())
    assert set(buttons) == {"Back", "All circuits"}


def test_sdp_list_and_detail_link_their_stps():
    spectrum = SpectrumView(rows=[SpectrumRow(subscription_id="sdp-1")])
    with (
        patch("amiss.frontend.sdp.get_sdps", return_value=SdpReconciliation(rows=_SDP_ROWS)),
        patch("amiss.frontend.sdp.get_sdp_detail", return_value=(SdpReconciliation(rows=_SDP_ROWS), spectrum)),
    ):
        pages = [client.get(path).text for path in ("/api/sdp", "/api/sdp/sdp-1/")]
    assert all("/stp/{stp_a_subscription_id}/" in page and "/stp/{stp_z_subscription_id}/" in page for page in pages)


def test_spectrum_links_the_sdp_ends():
    with patch("amiss.frontend.spectrum.get_spectrum", return_value=SpectrumView(rows=[_SDP])):
        response = client.get("/api/spectrum")
    assert "/stp/{stp_a_subscription_id}/" in response.text


def test_topology_list_links_the_provider():
    rows = [
        NamedRow(object_id="dom:topo", status=ReconcileStatus.DDS_ONLY, provider_nsa=_SUPA, provider_name="SURF uPA")
    ]
    with patch("amiss.data.get_topologies", return_value=NamedReconciliation(rows=rows)):
        page = client.get("/api/topology").json()
    table = next(n for n in _walk(page) if n.get("type") == "Table")
    assert table["data"][0]["provider_name"] == "SURF uPA"
    assert "/providers/{provider_nsa}/" in str(table["columns"])


def test_switching_service_list_has_no_provider_column():
    with patch("amiss.data.get_switching_services", return_value=NamedReconciliation(rows=[])):
        page = client.get("/api/switching-service").json()
    table = next(n for n in _walk(page) if n.get("type") == "Table")
    assert "provider_name" not in str(table["columns"])
