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


def get_dds_proxy_list(proxy_url: HttpUrl, path: str) -> bytes | None:
    """Fetch a DDS proxy collection endpoint; ``None`` if the request failed."""
    return nsi_util_get_json(HttpUrl(f"{str(proxy_url).rstrip('/')}{path}"), {})


def get_dds_proxy_topologies(proxy_url: HttpUrl) -> bytes | None:
    """Fetch all topologies from the DDS proxy (``GET /topologies``)."""
    return get_dds_proxy_list(proxy_url, "/topologies")


def get_dds_proxy_switching_services(proxy_url: HttpUrl) -> bytes | None:
    """Fetch all switching services from the DDS proxy (``GET /switching-services``)."""
    return get_dds_proxy_list(proxy_url, "/switching-services")


def get_dds_proxy_stps(proxy_url: HttpUrl) -> bytes | None:
    """Fetch all service termination points from the DDS proxy (``GET /service-termination-points``)."""
    return get_dds_proxy_list(proxy_url, "/service-termination-points")


def get_dds_proxy_sdps(proxy_url: HttpUrl) -> bytes | None:
    """Fetch all service demarcation points from the DDS proxy (``GET /service-demarcation-points``)."""
    return get_dds_proxy_list(proxy_url, "/service-demarcation-points")
