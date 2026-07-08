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

"""Data accessor the frontend routes call to get table rows.

In the default live mode this queries the WFO (forwarding the caller's OIDC token) and the DDS proxy
per request. ``NSI_AMISS_DATABASE_ENABLED`` is intended to switch to reading a database cache filled
by the scheduler; that read path is not implemented yet (needs a WFO service identity for the poller),
so it currently serves live regardless — see the plan's DB-cache follow-up.
"""

import structlog

from amiss.settings import settings
from amiss.sources.dds_topology import fetch_dds_sdps, fetch_dds_stps
from amiss.sources.reconcile import SdpReconciliation, StpReconciliation, reconcile_sdps, reconcile_stps
from amiss.sources.wfo import CircuitRow, fetch_circuits, fetch_sdp_subscriptions, fetch_stp_subscriptions

logger = structlog.get_logger(__name__)

if settings.NSI_AMISS_DATABASE_ENABLED:
    logger.warning("NSI_AMISS_DATABASE_ENABLED is set but DB-backed serving is not implemented yet; serving live")


def get_circuits(token: str | None) -> list[CircuitRow] | None:
    """Return the circuit rows, or ``None`` if the WFO could not be reached."""
    return fetch_circuits(token)


def get_stps(token: str | None) -> StpReconciliation:
    """Return the STP rows reconciled between the WFO subscriptions and the DDS topology."""
    return reconcile_stps(fetch_stp_subscriptions(token), fetch_dds_stps())


def get_sdps(token: str | None) -> SdpReconciliation:
    """Return the SDP rows reconciled between the WFO subscriptions and the DDS topology."""
    return reconcile_sdps(fetch_sdp_subscriptions(token), fetch_dds_sdps())
