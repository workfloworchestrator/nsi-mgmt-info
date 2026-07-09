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

"""Tests for amiss.frontend.util: token extraction and row sorting."""

from types import SimpleNamespace

import pytest

from amiss.frontend.util import sort_rows, token_from_request


class _Request:
    def __init__(self, headers):
        self.headers = headers


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        pytest.param({"X-Auth-Request-Access-Token": "xar"}, "xar", id="x-auth-request-header"),
        pytest.param({"X-Forwarded-Access-Token": "fwd"}, "fwd", id="forwarded-header"),
        pytest.param({"Authorization": "Bearer abc"}, "abc", id="bearer-fallback"),
        pytest.param({"Authorization": "bearer abc"}, "abc", id="bearer-case-insensitive"),
        pytest.param(
            {"X-Auth-Request-Access-Token": "xar", "X-Forwarded-Access-Token": "fwd", "Authorization": "Bearer abc"},
            "xar",
            id="x-auth-request-wins",
        ),
        pytest.param({"Authorization": "Basic xyz"}, None, id="non-bearer"),
        pytest.param({}, None, id="no-token"),
    ],
)
def test_token_from_request(headers, expected):
    assert token_from_request(_Request(headers)) == expected


def _row(**kwargs):
    return SimpleNamespace(**kwargs)


class TestSortRows:
    def test_none_leaves_order_unchanged(self):
        rows = [_row(state="b"), _row(state="a")]
        assert sort_rows(rows, None) == rows

    def test_sorts_case_insensitively(self):
        rows = [_row(state="Zeta"), _row(state="alpha")]
        assert [r.state for r in sort_rows(rows, "state")] == ["alpha", "Zeta"]

    def test_missing_values_sort_last(self):
        rows = [_row(state=None), _row(state="active"), _row(state=None)]
        assert [r.state for r in sort_rows(rows, "state")] == ["active", None, None]
