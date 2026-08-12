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

"""Tests for amiss.sources.wfo: GraphQL fetch + mapping to render DTOs (mocked HTTP)."""

import json
from unittest.mock import patch

import pytest
import requests

from amiss.sources import wfo

ACTIVE_SUBSCRIPTION = {
    "subscriptionId": "sub-1",
    "description": "subscription description",
    "status": "active",
    "startDate": "2026-07-01T10:00:00+00:00",
    "endDate": None,
    "vc": {
        "circuitDescription": "circuit A-Z",
        "serviceSpeed": 1000,
        "globalReservationId": "urn:uuid:1111",
        "connectionId": "conn-1",
        "state": "ACTIVE",
        "saps": [
            {"vlan": "100", "stp": {"stpId": "urn:ogf:network:a", "stpName": "Port A", "labelGroup": "1-4094"}},
            {"vlan": "200", "stp": {"stpId": "urn:ogf:network:z", "stpName": "Port Z", "labelGroup": "1-4094"}},
        ],
    },
    "processes": {
        "page": [{"createdBy": "alice", "startedAt": "2026-06-30T09:00:00+00:00", "lastStatus": "completed"}]
    },
}

# Terminated: the single nullable GraphQL type means vc (and its scalars) can be null — must not crash.
TERMINATED_SUBSCRIPTION = {
    "subscriptionId": "sub-2",
    "description": "terminated circuit",
    "status": "terminated",
    "startDate": "2026-06-01T00:00:00+00:00",
    "endDate": "2026-06-15T00:00:00+00:00",
    "vc": None,
    "processes": {"page": []},
}

# Provisioning with only the source SAP present so far.
PARTIAL_SUBSCRIPTION = {
    "subscriptionId": "sub-3",
    "description": "half built",
    "status": "provisioning",
    "vc": {"serviceSpeed": None, "state": None, "saps": [{"vlan": "300", "stp": {"stpId": "urn:ogf:network:a"}}]},
    "processes": {"page": [{"createdBy": "bob", "lastStatus": "running"}]},
}


class TestMapCircuit:
    @pytest.mark.parametrize(
        ("subscription", "expected"),
        [
            pytest.param(
                ACTIVE_SUBSCRIPTION,
                {
                    "subscription_id": "sub-1",
                    "description": "circuit A-Z",
                    "source_stp": "Port A",
                    "source_vlan": "100",
                    "dest_stp": "Port Z",
                    "dest_vlan": "200",
                    "source": "Port A (vlan 100)",  # merged stp+vlan for the compact list
                    "dest": "Port Z (vlan 200)",
                    "bandwidth": 1000,
                    "state": "ACTIVE",
                    "created_by": "alice",
                    "connection_id": "conn-1",
                },
                id="active-full",
            ),
            pytest.param(
                TERMINATED_SUBSCRIPTION,
                {
                    "subscription_id": "sub-2",
                    "description": "terminated circuit",  # falls back to subscription description
                    "source_stp": None,
                    "dest_stp": None,
                    "bandwidth": None,
                    "state": "terminated",  # falls back to subscription status
                    "created_by": None,
                },
                id="terminated-null-vc",
            ),
            pytest.param(
                PARTIAL_SUBSCRIPTION,
                {
                    "subscription_id": "sub-3",
                    "source_stp": "urn:ogf:network:a",  # no stpName -> stpId
                    "source_vlan": "300",
                    "dest_stp": None,  # only one SAP
                    "dest_vlan": None,
                    "source": "urn:ogf:network:a (vlan 300)",
                    "dest": None,  # only one SAP -> no destination label
                    "created_by": "bob",  # no completed CREATE -> first CREATE
                },
                id="partial-one-sap",
            ),
        ],
    )
    def test_maps_fields(self, subscription, expected):
        row = wfo._map_circuit(subscription)
        for field, value in expected.items():
            assert getattr(row, field) == value

    def test_formats_dates_compactly(self):
        # ISO with T/offset -> 'YYYY-MM-DD HH:MM:SS' (no T, no microseconds/timezone)
        row = wfo._map_circuit(TERMINATED_SUBSCRIPTION)
        assert row.start_time == "2026-06-01 00:00:00"
        assert row.end_time == "2026-06-15 00:00:00"

    def test_short_id_is_first_8_chars(self):
        row = wfo._map_circuit({"subscriptionId": "abcdef12-3456-7890-abcd-ef1234567890"})
        assert row.short_id == "abcdef12" and row.subscription_id == "abcdef12-3456-7890-abcd-ef1234567890"


class TestCreatedBy:
    @pytest.mark.parametrize(
        ("processes_page", "expected"),
        [
            pytest.param(
                [
                    {"createdBy": "failed-run", "lastStatus": "failed"},
                    {"createdBy": "good-run", "lastStatus": "completed"},
                ],
                "good-run",
                id="prefers-completed-over-earlier-failed",
            ),
            pytest.param([{"createdBy": "only-run", "lastStatus": "failed"}], "only-run", id="falls-back-to-first"),
            pytest.param([], None, id="no-create-process"),
        ],
    )
    def test_selects_creator(self, processes_page, expected):
        assert wfo._created_by({"processes": {"page": processes_page}}) == expected

    def test_missing_processes_key(self):
        assert wfo._created_by({}) is None

    @pytest.mark.parametrize(
        ("created_by", "expected"),
        [
            pytest.param("Ada Lovelace <ada@example.org>", "Ada Lovelace", id="name-and-email"),
            pytest.param("Ada Lovelace", "Ada Lovelace", id="name-only"),
            pytest.param("ada@example.org", "ada@example.org", id="email-only"),
            pytest.param(None, None, id="unknown-creator"),
        ],
    )
    def test_created_by_name_drops_the_email(self, created_by, expected):
        assert wfo.CircuitRow(subscription_id="x", created_by=created_by).created_by_name == expected


def test_page_warns_on_truncation():
    data = {"subscriptions": {"page": [{"subscriptionId": "x"}], "pageInfo": {"totalItems": 5}}}
    with patch.object(wfo.logger, "warning") as warn:
        page = wfo._page(data)
    assert len(page) == 1
    warn.assert_called_once()


class _FakeResponse:
    def __init__(self, status_code=200, content=b'{"data": {"ok": true}}', reason="OK"):
        self.status_code = status_code
        self.content = content
        self.reason = reason


class TestQueryWfo:
    @pytest.mark.parametrize(
        "response",
        [
            pytest.param(_FakeResponse(status_code=500, reason="err"), id="non-200"),
            pytest.param(_FakeResponse(content=b"<html>"), id="non-json"),
            pytest.param(_FakeResponse(content=b"[]"), id="not-an-object"),
            pytest.param(
                _FakeResponse(content=json.dumps({"errors": [{"message": "Cannot query field 'nope'"}]}).encode()),
                id="graphql-errors",
            ),
        ],
    )
    def test_returns_none_on_failure(self, response):
        with patch.object(wfo.session, "post", return_value=response):
            assert wfo.query_wfo("{ x }", "t") is None

    @pytest.mark.parametrize(
        "response",
        [
            pytest.param(_FakeResponse(status_code=401), id="http-401"),
            pytest.param(_FakeResponse(status_code=403), id="http-403"),
            pytest.param(
                _FakeResponse(content=json.dumps({"errors": [{"message": "not_authenticated"}]}).encode()),
                id="bare-underscored-message",
            ),
            pytest.param(
                _FakeResponse(
                    content=json.dumps({"errors": [{"message": "User is not authorized to query `x`"}]}).encode()
                ),
                id="worded-message",
            ),
            pytest.param(
                _FakeResponse(
                    content=json.dumps(
                        {"errors": [{"message": "boom", "extensions": {"error_type": "not_authorized"}}]}
                    ).encode()
                ),
                id="error-type-extension",
            ),
        ],
    )
    def test_raises_unauthorized_when_credentials_are_refused(self, response):
        """A refusal is not an outage: the caller reached the WFO and only lacks the read group."""
        with patch.object(wfo.session, "post", return_value=response), pytest.raises(wfo.WfoUnauthorizedError):
            wfo.query_wfo("{ x }", "t")

    def test_returns_none_on_transport_error(self):
        with patch.object(wfo.session, "post", side_effect=requests.exceptions.ReadTimeout("slow")):
            assert wfo.query_wfo("{ x }", "t") is None

    def test_returns_data_and_forwards_bearer(self):
        ok = _FakeResponse(content=json.dumps({"data": {"subscriptions": {"page": []}}}).encode())
        with patch.object(wfo.session, "post", return_value=ok) as post:
            data = wfo.query_wfo("{ x }", "my-token")
        assert data == {"subscriptions": {"page": []}}
        assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer my-token"

    def test_omits_authorization_without_token(self):
        ok = _FakeResponse(content=json.dumps({"data": {}}).encode())
        with patch.object(wfo.session, "post", return_value=ok) as post:
            wfo.query_wfo("{ x }", None)
        assert "Authorization" not in post.call_args.kwargs["headers"]


STP_SUBSCRIPTION = {
    "subscriptionId": "stp-1",
    "status": "active",
    "stp": {"stpId": "urn:ogf:network:port-a", "stpName": "Port A", "capacity": 10000, "labelGroup": "1000-1999"},
}

SDP_SUBSCRIPTION = {
    "subscriptionId": "sdp-1",
    "status": "active",
    "sdp": {
        "sdpName": "A<->B",
        "stps": [
            {"stpId": "urn:ogf:network:port-a", "stpName": "Port A", "labelGroup": "1000-1999"},
            {"stpId": "urn:ogf:network:port-b", "stpName": "Port B", "labelGroup": "1000-1999"},
        ],
    },
}


class TestMapStp:
    def test_maps_fields(self):
        stp = wfo._map_stp(STP_SUBSCRIPTION)
        assert (stp.subscription_id, stp.stp_id, stp.stp_name, stp.capacity, stp.label_group, stp.status) == (
            "stp-1",
            "urn:ogf:network:port-a",
            "Port A",
            10000,
            "1000-1999",
            "active",
        )

    def test_tolerates_missing_block(self):
        stp = wfo._map_stp({"subscriptionId": "stp-x", "status": "initial"})
        assert stp.subscription_id == "stp-x" and stp.stp_id is None and stp.status == "initial"


class TestMapSdp:
    def test_maps_name_and_members(self):
        sdp = wfo._map_sdp(SDP_SUBSCRIPTION)
        assert sdp.subscription_id == "sdp-1" and sdp.sdp_name == "A<->B"
        assert [m.stp_id for m in sdp.stps] == ["urn:ogf:network:port-a", "urn:ogf:network:port-b"]

    def test_tolerates_missing_block(self):
        sdp = wfo._map_sdp({"subscriptionId": "sdp-x", "status": "initial"})
        assert sdp.stps == [] and sdp.sdp_name is None


class TestFetch:
    @pytest.mark.parametrize(
        "fetch",
        [wfo.fetch_circuits, wfo.fetch_stp_subscriptions, wfo.fetch_sdp_subscriptions],
        ids=["circuits", "stp", "sdp"],
    )
    def test_returns_none_on_failure(self, fetch):
        with patch.object(wfo, "query_wfo", return_value=None):
            assert fetch("t") is None

    @pytest.mark.parametrize(
        ("fetch", "subscription", "expected_id"),
        [
            pytest.param(wfo.fetch_circuits, ACTIVE_SUBSCRIPTION, "sub-1", id="circuits"),
            pytest.param(wfo.fetch_stp_subscriptions, STP_SUBSCRIPTION, "stp-1", id="stp"),
            pytest.param(wfo.fetch_sdp_subscriptions, SDP_SUBSCRIPTION, "sdp-1", id="sdp"),
        ],
    )
    def test_maps_page(self, fetch, subscription, expected_id):
        data = {"subscriptions": {"page": [subscription], "pageInfo": {"totalItems": 1}}}
        with patch.object(wfo, "query_wfo", return_value=data):
            rows = fetch("t")
        assert [r.subscription_id for r in rows] == [expected_id]
