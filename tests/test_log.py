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

"""Tests for amiss.log: UvicornAccessLogFilter."""

from logging import LogRecord

import pytest

from amiss.log import UvicornAccessLogFilter


class TestUvicornAccessLogFilter:
    @pytest.mark.parametrize(
        ("args", "expected"),
        [
            pytest.param(("127.0.0.1", "GET", "/healthcheck"), False, id="healthcheck-filtered"),
            pytest.param(("127.0.0.1", "GET", "/api/circuits"), True, id="other-endpoint-passes"),
            pytest.param(None, True, id="none-args-passes"),
            pytest.param(("127.0.0.1",), True, id="short-args-passes"),
            pytest.param((), True, id="empty-tuple-passes"),
        ],
    )
    def test_filter(self, args, expected):
        filt = UvicornAccessLogFilter()
        record = LogRecord("uvicorn.access", 20, "test.py", 1, "msg", (), None)
        record.args = args
        assert filt.filter(record) is expected
