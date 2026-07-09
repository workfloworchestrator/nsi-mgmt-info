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

"""Tests for amiss.dds: URN stripping and DDS-proxy fetch helpers."""

from unittest.mock import patch

import pytest
from pydantic import HttpUrl

from amiss.dds import get_dds_proxy_sdps, get_dds_proxy_stps, strip_urn


class TestStripUrn:
    @pytest.mark.parametrize(
        ("urn", "expected"),
        [
            pytest.param("urn:ogf:network:surf.example:2024:net:port", "surf.example:2024:net:port", id="with-prefix"),
            pytest.param("surf.example:2024:net:port", "surf.example:2024:net:port", id="without-prefix"),
            pytest.param("urn:ogf:network:", "", id="only-prefix"),
        ],
    )
    def test_strip_urn(self, urn, expected):
        assert strip_urn(urn) == expected


@pytest.mark.parametrize(
    ("fetch", "path"),
    [
        pytest.param(get_dds_proxy_stps, "service-termination-points", id="stps"),
        pytest.param(get_dds_proxy_sdps, "service-demarcation-points", id="sdps"),
    ],
)
class TestGetDdsProxy:
    @patch("amiss.dds.nsi_util_get_json")
    def test_appends_path_and_empty_queryparams(self, mock_get_json, fetch, path):
        mock_get_json.return_value = b"[]"
        result = fetch(HttpUrl("http://proxy.example/dds-proxy/"))
        called_url, called_params = mock_get_json.call_args.args
        assert str(called_url) == f"http://proxy.example/dds-proxy/{path}"
        assert called_params == {}
        assert result == b"[]"

    @patch("amiss.dds.nsi_util_get_json")
    def test_handles_base_url_without_trailing_slash(self, mock_get_json, fetch, path):
        fetch(HttpUrl("http://proxy.example/dds-proxy"))
        called_url, _ = mock_get_json.call_args.args
        assert str(called_url) == f"http://proxy.example/dds-proxy/{path}"

    @patch("amiss.dds.nsi_util_get_json")
    def test_returns_none_when_request_fails(self, mock_get_json, fetch, path):
        mock_get_json.return_value = None
        assert fetch(HttpUrl("http://proxy.example/")) is None
        assert str(mock_get_json.call_args.args[0]).endswith(path)
