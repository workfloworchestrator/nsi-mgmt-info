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

"""Fetch the DDS-proxy topology as plain reconciliation DTOs (no database writes).

This is the read-only counterpart to amiss/dds.py's poller helpers: it maps the DDS proxy JSON into
``DdsStp``/``DdsSdp`` for live reconciliation against the WFO. Each fetch returns ``None`` on failure
so the reconciler can tell a failed source apart from an empty one.
"""

import json

import structlog

from amiss.dds import get_dds_proxy_sdps, get_dds_proxy_stps, strip_urn
from amiss.settings import settings
from amiss.sources.reconcile import DdsSdp, DdsStp

logger = structlog.get_logger(__name__)


def _parse_list(raw: bytes | None, what: str) -> list | None:
    """Parse a DDS proxy JSON body into a list, or ``None`` on failure."""
    if raw is None:
        return None
    try:
        items = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("cannot parse DDS proxy response", what=what, error=str(e))
        return None
    if not isinstance(items, list):
        logger.warning("DDS proxy response is not a list", what=what)
        return None
    return items


def _to_dds_stp(item: dict) -> DdsStp | None:
    stp_id = item.get("id")
    return (
        DdsStp(stp_id=strip_urn(stp_id), vlan_range=item.get("labelGroup"), description=item.get("name"))
        if stp_id
        else None
    )


def _to_dds_sdp(item: dict) -> DdsSdp | None:
    stp_a, stp_z = item.get("stpAId"), item.get("stpZId")
    return DdsSdp(stp_a_id=strip_urn(stp_a), stp_z_id=strip_urn(stp_z)) if stp_a and stp_z else None


def fetch_dds_stps() -> list[DdsStp] | None:
    """Fetch the DDS-proxy STP topology, or ``None`` on failure."""
    items = _parse_list(get_dds_proxy_stps(settings.NSI_DDS_PROXY_URL), "STPs")
    return None if items is None else [stp for item in items if (stp := _to_dds_stp(item))]


def fetch_dds_sdps() -> list[DdsSdp] | None:
    """Fetch the DDS-proxy SDP topology (STP-pair only), or ``None`` on failure."""
    items = _parse_list(get_dds_proxy_sdps(settings.NSI_DDS_PROXY_URL), "SDPs")
    return None if items is None else [sdp for item in items if (sdp := _to_dds_sdp(item))]
