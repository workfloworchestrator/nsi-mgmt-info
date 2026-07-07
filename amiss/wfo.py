# Copyright 2024-2025 SURF.
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

# Reference: serving GraphQL over HTTP — https://graphql.org/learn/serving-over-http/

import json
from urllib.parse import quote

import structlog
from pydantic import HttpUrl

from amiss.nsi import nsi_util_get_json
from amiss.settings import settings

logger = structlog.get_logger(__name__)

# Hard-coded GraphQL query (multi-line for readability / future alteration). It is collapsed to a
# single line and URL-escaped before being appended to the endpoint as ?query=.
# TODO: placeholder Node query — replace with the reservation/MDP2P query once defined.
WFO_RESERVATIONS_QUERY = """{
  subscriptions(filterBy: {field: "type", value: "Node"}) {
    page {
      ... on NodeSubscription {
        subscriptionId
        description
        node {
          name
        }
      }
    }
  }
}"""


def pull_reservations_from_wfo() -> dict | None:
    """Query the WFO GraphQL API. Returns the parsed ``data`` on success, or ``None`` on error.

    Builds ``<NSI_AMISS_WFO_URL>/api/graphql?query=<single-line, URL-escaped WFO_RESERVATIONS_QUERY>``
    and fetches it with ``nsi_util_get_json``. A GraphQL ``errors`` payload (e.g. the current
    ``not_authenticated`` response, since auth is not wired yet) is logged and yields ``None``.
    """
    log = logger.bind()
    single_line_query = " ".join(WFO_RESERVATIONS_QUERY.split())
    url = HttpUrl(
        f"{str(settings.NSI_AMISS_WFO_URL).rstrip('/')}/api/graphql?query={quote(single_line_query, safe='')}"
    )

    raw = nsi_util_get_json(url, {})
    if raw is None:
        return None  # nsi_util_get_json already logged the reason
    try:
        result = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        log.warning("cannot parse WFO GraphQL response", url=str(url), error=str(e))
        return None
    if not isinstance(result, dict):
        log.warning("WFO GraphQL response is not a JSON object", url=str(url))
        return None
    if result.get("errors"):
        log.warning("WFO GraphQL returned errors", errors=result["errors"])
        return None
    data = result.get("data")
    return data if isinstance(data, dict) else None
