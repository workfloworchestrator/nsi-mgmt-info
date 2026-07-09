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

"""Tests for amiss.nsi proxy authentication kwargs and JSON fetching."""

from unittest.mock import patch

import pytest
import requests
from pydantic import HttpUrl

from amiss import nsi
from amiss.settings import settings


class _FakeResponse:
    def __init__(self, status_code=200, content_type="application/json", content=b"{}", reason="OK"):
        self.status_code = status_code
        self.headers = {} if content_type is None else {"content-type": content_type}
        self.content = content
        self.reason = reason


def test_header_auth_when_mtls_disabled(monkeypatch):
    """Without mTLS, requests carry the edge-identity headers and no client cert."""
    monkeypatch.setattr(settings, "NSI_PROXY_MTLS_ENABLED", False)
    monkeypatch.setattr(settings, "NSI_PROXY_AUTH_METHOD", "x509")
    monkeypatch.setattr(settings, "NSI_PROXY_CLIENT_DN", "CN=nsi-mgmt-info")
    assert nsi._request_auth_kwargs() == {"headers": {"X-Auth-Method": "x509", "X-Client-DN": "CN=nsi-mgmt-info"}}


def test_mtls_disabled_needs_no_cert_files(monkeypatch):
    """With mTLS disabled the cert paths may be unset (the container has no PEM files)."""
    monkeypatch.setattr(settings, "NSI_PROXY_MTLS_ENABLED", False)
    monkeypatch.setattr(settings, "NSI_AMISS_CERTIFICATE", None)
    monkeypatch.setattr(settings, "NSI_AMISS_PRIVATE_KEY", None)
    assert "cert" not in nsi._request_auth_kwargs()


def test_mtls_enabled_uses_cert(monkeypatch, tmp_path):
    """With mTLS, the configured client cert/key are passed to requests."""
    cert = tmp_path / "cert.pem"
    cert.write_text("")
    key = tmp_path / "key.pem"
    key.write_text("")
    monkeypatch.setattr(settings, "NSI_PROXY_MTLS_ENABLED", True)
    monkeypatch.setattr(settings, "NSI_AMISS_CERTIFICATE", cert)
    monkeypatch.setattr(settings, "NSI_AMISS_PRIVATE_KEY", key)
    assert nsi._request_auth_kwargs()["cert"] == (str(cert), str(key))


def test_mtls_enabled_without_cert_raises(monkeypatch):
    """MTLS on but no cert configured is a misconfiguration, not a silent header fallback."""
    monkeypatch.setattr(settings, "NSI_PROXY_MTLS_ENABLED", True)
    monkeypatch.setattr(settings, "NSI_AMISS_CERTIFICATE", None)
    monkeypatch.setattr(settings, "NSI_AMISS_PRIVATE_KEY", None)
    with pytest.raises(RuntimeError):
        nsi._request_auth_kwargs()


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        pytest.param("application/json", b"{}", id="plain-json"),
        pytest.param("application/graphql-response+json", b"{}", id="graphql-json"),
        pytest.param("application/json; charset=utf-8", b"{}", id="json-with-charset"),
        pytest.param("text/html", None, id="html-rejected"),
        pytest.param(None, None, id="missing-header"),
    ],
)
def test_get_json_accepts_json_media_types(monkeypatch, content_type, expected):
    """JSON and graphql-response+json (with optional charset) are accepted; other types return None."""
    monkeypatch.setattr(settings, "NSI_PROXY_MTLS_ENABLED", False)
    with patch.object(nsi.session, "get", return_value=_FakeResponse(content_type=content_type)) as mock_get:
        result = nsi.nsi_util_get_json(HttpUrl("http://proxy.example/x"), {})
    assert result == expected
    assert mock_get.call_args.kwargs["timeout"] == nsi.REQUEST_TIMEOUT


def test_get_json_returns_none_on_timeout(monkeypatch):
    """A read timeout is logged and yields None rather than propagating."""
    monkeypatch.setattr(settings, "NSI_PROXY_MTLS_ENABLED", False)
    with patch.object(nsi.session, "get", side_effect=requests.exceptions.ReadTimeout("slow")):
        assert nsi.nsi_util_get_json(HttpUrl("http://proxy.example/x"), {}) is None
