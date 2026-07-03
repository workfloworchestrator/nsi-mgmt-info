# Copyright 2024-2026 SURF.
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

"""Tests for amiss.wfo: pull_reservations_from_wfo (mocked HTTP)."""

import json
from unittest.mock import patch

NOT_AUTHENTICATED = json.dumps(
    {
        "data": None,
        "errors": [
            {
                "message": "User is not authenticated",
                "locations": [{"line": 2, "column": 3}],
                "path": ["subscriptions"],
                "extensions": {"error_type": "not_authenticated"},
            }
        ],
    }
).encode()


class TestPullReservationsFromWfo:
    @patch("amiss.wfo.nsi_util_get_json")
    def test_returns_none_on_graphql_errors(self, mock_get):
        from amiss.wfo import pull_reservations_from_wfo

        mock_get.return_value = NOT_AUTHENTICATED
        assert pull_reservations_from_wfo() is None

    @patch("amiss.wfo.nsi_util_get_json")
    def test_returns_data_on_success(self, mock_get):
        from amiss.wfo import pull_reservations_from_wfo

        data = {"subscriptions": {"page": [{"subscriptionId": "abc", "description": "node-1", "node": {"name": "n1"}}]}}
        mock_get.return_value = json.dumps({"data": data, "errors": None}).encode()
        assert pull_reservations_from_wfo() == data

    @patch("amiss.wfo.nsi_util_get_json")
    def test_returns_none_when_fetch_fails(self, mock_get):
        from amiss.wfo import pull_reservations_from_wfo

        mock_get.return_value = None
        assert pull_reservations_from_wfo() is None

    @patch("amiss.wfo.nsi_util_get_json")
    def test_returns_none_on_invalid_json(self, mock_get):
        from amiss.wfo import pull_reservations_from_wfo

        mock_get.return_value = b"<html>not json</html>"
        assert pull_reservations_from_wfo() is None

    @patch("amiss.wfo.nsi_util_get_json")
    def test_builds_escaped_graphql_url_with_empty_queryparams(self, mock_get):
        from amiss.wfo import pull_reservations_from_wfo

        mock_get.return_value = NOT_AUTHENTICATED
        pull_reservations_from_wfo()

        called_url, called_params = mock_get.call_args.args
        url_str = str(called_url)
        assert "/api/graphql?query=" in url_str
        assert "%7B" in url_str  # the query's "{" is URL-escaped
        assert "subscriptions" in url_str  # single-lined query is present
        assert called_params == {}
