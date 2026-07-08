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

    def test_parses_dates(self):
        row = wfo._map_circuit(TERMINATED_SUBSCRIPTION)
        assert row.start_time.year == 2026 and row.start_time.month == 6
        assert row.end_time.day == 15


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
                _FakeResponse(content=json.dumps({"errors": [{"message": "not_authenticated"}]}).encode()),
                id="graphql-errors",
            ),
        ],
    )
    def test_returns_none_on_failure(self, response):
        with patch.object(wfo.session, "post", return_value=response):
            assert wfo.query_wfo("{ x }", "t") is None

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


class TestFetch:
    def test_fetch_circuits_none_on_failure(self):
        with patch.object(wfo, "query_wfo", return_value=None):
            assert wfo.fetch_circuits("t") is None

    def test_fetch_circuits_maps_page(self):
        data = {"subscriptions": {"page": [ACTIVE_SUBSCRIPTION], "pageInfo": {"totalItems": 1}}}
        with patch.object(wfo, "query_wfo", return_value=data):
            rows = wfo.fetch_circuits("t")
        assert [r.subscription_id for r in rows] == ["sub-1"]
