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

from typing import Any

import requests
import requests.exceptions
import structlog
from pydantic import HttpUrl
from urllib3.util.retry import Retry

from amiss.settings import settings

logger = structlog.get_logger(__name__)


#
# Library
#

requests_session_adapter = requests.adapters.HTTPAdapter(max_retries=Retry(connect=3, backoff_factor=0.1))
session = requests.Session()
session.mount("http://", requests_session_adapter)
session.mount("https://", requests_session_adapter)

# (connect, read) timeout in seconds for outbound HTTP requests.
REQUEST_TIMEOUT: tuple[float, float] = (5.0, 30.0)

# Response media types accepted as JSON (application/graphql-response+json is used by GraphQL over HTTP).
JSON_MEDIA_TYPES = frozenset({"application/json", "application/graphql-response+json"})


def _request_auth_kwargs() -> dict[str, Any]:
    """Build the authentication kwargs for proxy requests: mutual TLS, or local-dev headers.

    Production uses mutual TLS. With ``NSI_PROXY_MTLS_ENABLED=false`` (local dev against
    port-forwarded proxies) the edge-identity headers the ingress would otherwise inject are sent
    instead, matching nsi-orchestrator's ``services/edge_auth.py``.
    """
    if settings.NSI_PROXY_MTLS_ENABLED:
        if settings.NSI_AMISS_CERTIFICATE is None or settings.NSI_AMISS_PRIVATE_KEY is None:
            raise RuntimeError("NSI_PROXY_MTLS_ENABLED is true but NSI_AMISS_CERTIFICATE/PRIVATE_KEY are unset")
        return {
            "verify": settings.verify,
            "cert": (str(settings.NSI_AMISS_CERTIFICATE), str(settings.NSI_AMISS_PRIVATE_KEY)),
        }
    return {"headers": {"X-Auth-Method": settings.NSI_PROXY_AUTH_METHOD, "X-Client-DN": settings.NSI_PROXY_CLIENT_DN}}


def nsi_util_get_json(url: HttpUrl, queryparams: dict) -> bytes | None:
    """Fetch JSON from a proxy endpoint; return the raw response body as bytes, or None on failure.

    A 401/403 is deliberately just another failure here, unlike on the WFO leg (which raises
    ``WfoUnauthorizedError``): these requests carry AMISS's own identity, not the end user's, so a
    refusal is a deployment fault affecting everyone and nothing the caller can act on.
    """
    log = logger.bind()

    log.debug("SENDING HTTP REQUEST FOR JSON", url=str(url))
    try:
        r = session.get(str(url), params=queryparams, timeout=REQUEST_TIMEOUT, **_request_auth_kwargs())
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        log.warning("cannot get JSON document", url=str(url), error=str(e))
        return None

    if r.status_code != 200:
        log.warning(f"{url} returned {r.status_code} with message {r.reason}")
        return None
    media_type = r.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type not in JSON_MEDIA_TYPES:
        log.warning(f"{url} did not return JSON but {media_type!r}")
        return None
    return r.content
