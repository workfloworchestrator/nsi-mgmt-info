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

"""Integration tests driving the full stack with the WFO/DDS transport mocked by ``responses``.

Exercises the real route -> data -> sources -> HTTP path: GraphQL query building, JSON parsing,
mapping, and reconciliation — everything except the socket — against captured-shape payloads.
"""

import json

import pytest
import responses
from fastapi.testclient import TestClient

from amiss import app
from amiss.settings import settings

client = TestClient(app)

WFO_GRAPHQL = "http://orchestrator.domain.example/api/graphql"
DDS = "http://dds.domain.example/dds"

# --- Upstream payloads (typed WFO shape + DDS-proxy topology) --------------------------------------

CIRCUIT = {
    "subscriptionId": "c1",
    "description": "AMS-NYC",
    "status": "active",
    "startDate": "2026-07-01T10:00:00+00:00",
    "endDate": None,
    "vc": {
        "circuitDescription": "AMS-NYC",
        "serviceSpeed": 10,
        "globalReservationId": "urn:uuid:1",
        "connectionId": "conn-1",
        "state": "ACTIVATED",
        "saps": [
            {"vlan": "100", "stp": {"stpId": "urn:ogf:network:port-a", "stpName": "Port A", "labelGroup": "1-4094"}},
            {"vlan": "200", "stp": {"stpId": "urn:ogf:network:port-z", "stpName": "Port Z", "labelGroup": "1-4094"}},
        ],
    },
    "processes": {
        "page": [{"createdBy": "alice", "startedAt": "2026-06-30T09:00:00+00:00", "lastStatus": "completed"}]
    },
}

STPS = [
    {"subscriptionId": "s-a", "status": "active",
     "stp": {"stpId": "urn:ogf:network:port-a", "stpName": "Port A", "capacity": 10000, "labelGroup": "1-4094"}},
    {"subscriptionId": "s-z", "status": "active",
     "stp": {"stpId": "urn:ogf:network:port-z", "stpName": "Port Z", "capacity": 10000, "labelGroup": "1-4094"}},
]  # fmt: skip

SDPS = [
    {"subscriptionId": "d1", "status": "active",
     "sdp": {"sdpName": "A<->B", "stps": [{"stpId": "urn:ogf:network:port-a"}, {"stpId": "urn:ogf:network:port-b"}]}},
]  # fmt: skip

DDS_STPS = [
    {"id": "urn:ogf:network:port-a", "labelGroup": "1-4094", "name": "Port A"},  # matches s-a -> IN_BOTH
    {"id": "urn:ogf:network:port-x", "labelGroup": "1-4094", "name": "Port X"},  # DDS only
]  # port-z is WFO-only -> MISSING_IN_DDS

DDS_SDPS = [
    {"stpAId": "urn:ogf:network:port-a", "stpZId": "urn:ogf:network:port-b"},  # matches d1 -> IN_BOTH
    {"stpAId": "urn:ogf:network:port-c", "stpZId": "urn:ogf:network:port-d"},  # DDS only
]


def _wfo_callback(request):
    """Route the single /api/graphql endpoint to a payload based on the query's tag filter."""
    query = json.loads(request.body)["query"]
    page = [CIRCUIT] if 'value: "MDP2P"' in query else STPS if 'value: "STP"' in query else SDPS
    body = {"data": {"subscriptions": {"page": page, "pageInfo": {"totalItems": len(page)}}}}
    return 200, {"Content-Type": "application/json"}, json.dumps(body)


@pytest.fixture
def upstreams(monkeypatch):
    # header auth to the DDS proxy so no client cert is needed in tests
    monkeypatch.setattr(settings, "NSI_PROXY_MTLS_ENABLED", False)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.add_callback(responses.POST, WFO_GRAPHQL, callback=_wfo_callback, content_type="application/json")
        mock.add(responses.GET, f"{DDS}/service-termination-points", json=DDS_STPS, content_type="application/json")
        mock.add(responses.GET, f"{DDS}/service-demarcation-points", json=DDS_SDPS, content_type="application/json")
        yield


def _get(path: str):
    # forward a token the way the portal's oauth2-proxy would, so query_wfo sends a Bearer credential
    return client.get(path, headers={"X-Auth-Request-Access-Token": "itoken"})


@pytest.mark.usefixtures("upstreams")
def test_circuits_render_from_wfo():
    response = _get("/api/circuits")
    assert response.status_code == 200
    # source/dest STP names from vc.saps, and the creator from the CREATE process
    assert "Port A" in response.text and "Port Z" in response.text and "alice" in response.text


@pytest.mark.usefixtures("upstreams")
def test_stp_reconciliation_all_three_states():
    response = _get("/api/stp")
    assert response.status_code == 200
    assert "backed by DDS" in response.text  # port-a: in both
    assert "DDS only" in response.text  # port-x: DDS only
    assert "subscription not in DDS" in response.text  # port-z: WFO only


@pytest.mark.usefixtures("upstreams")
def test_sdp_reconciliation():
    response = _get("/api/sdp")
    assert response.status_code == 200
    assert "backed by DDS" in response.text and "DDS only" in response.text


@pytest.mark.usefixtures("upstreams")
def test_dashboard_aggregates_all_sources():
    response = _get("/api/")
    assert response.status_code == 200
    assert "Circuits" in response.text
    assert "Termination Points" in response.text and "backed by DDS" in response.text
