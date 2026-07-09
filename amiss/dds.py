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

"""DDS-proxy topology fetch helpers, reused by amiss/sources/dds_topology.py."""

from pydantic import HttpUrl

from amiss.nsi import nsi_util_get_json


def strip_urn(urn: str) -> str:
    return urn.replace("urn:ogf:network:", "")


def get_dds_proxy_stps(proxy_url: HttpUrl) -> bytes | None:
    """Fetch all service termination points from the DDS proxy.

    Calls the proxy's ``GET /service-termination-points`` endpoint; ``proxy_url`` is the proxy base
    URL, the path is appended to it. Returns the raw JSON body as bytes, or ``None`` if the request
    failed (``nsi_util_get_json`` already logs the reason).
    """
    stps_url = HttpUrl(f"{str(proxy_url).rstrip('/')}/service-termination-points")
    return nsi_util_get_json(stps_url, {})


def get_dds_proxy_sdps(proxy_url: HttpUrl) -> bytes | None:
    """Fetch all service demarcation points from the DDS proxy.

    Calls the proxy's ``GET /service-demarcation-points`` endpoint; ``proxy_url`` is the proxy base
    URL, the path is appended to it. Returns the raw JSON body as bytes, or ``None`` if the request
    failed (``nsi_util_get_json`` already logs the reason).
    """
    sdps_url = HttpUrl(f"{str(proxy_url).rstrip('/')}/service-demarcation-points")
    return nsi_util_get_json(sdps_url, {})
