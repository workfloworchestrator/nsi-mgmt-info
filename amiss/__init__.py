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

import time
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastui import prebuilt_html
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, Response

from amiss.frontend.circuits import router as circuits_router
from amiss.frontend.healthcheck import router as healthcheck_router
from amiss.frontend.home import router as home_router
from amiss.frontend.sdp import router as sdp_router
from amiss.frontend.spectrum import router as spectrum_router
from amiss.frontend.stp import router as stp_router
from amiss.log import init as log_init
from amiss.settings import settings

#
# logging
#
log_init()
logger = structlog.get_logger(__name__)

#
# application
#
app = FastAPI()

# make sure the folder named 'static' exists in the project,
# and put the css and js files inside a subfolder called 'assets'
app.mount("/static", StaticFiles(directory=settings.STATIC_DIRECTORY), name="static")


@app.middleware("http")
async def log_request_time(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """Log wall-clock time per request (DEBUG) so page build latency is visible when profiling."""
    start = time.perf_counter()
    response = await call_next(request)
    logger.debug("request", path=request.url.path, elapsed_ms=round((time.perf_counter() - start) * 1000, 1))
    return response


# include routes
app.include_router(healthcheck_router)
app.include_router(circuits_router, prefix="/api/circuits")
app.include_router(stp_router, prefix="/api/stp")
app.include_router(sdp_router, prefix="/api/sdp")

app.include_router(spectrum_router, prefix="/api/spectrum")
app.include_router(home_router, prefix="/api")


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt() -> str:
    return "User-agent: *\nAllow: /"


@app.get("/favicon.ico", status_code=404, response_class=PlainTextResponse)
async def favicon_ico() -> str:
    return "page not found"


# Minimal brand styling to match the ANA portal (ana-automation-ui): teal navbar, light background,
# system font. FastUI's prebuilt page has no CSS hook and injects Bootstrap into <head> at runtime,
# so this is appended at the end of <body> (later in document order) with !important to win the cascade.
_BRAND_STYLE = """
<style>
  body { background-color: #f5f7fa !important;
         font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important; }
  .navbar { background-color: #2a5c5c !important; border-bottom: none !important; }
  .navbar .navbar-brand, .navbar .nav-link { color: #ffffff !important; }
  .navbar .nav-link.active { color: #57e0c4 !important; font-weight: 600 !important; }
  a, a:hover { color: #2a5c5c; }
</style>
"""


@app.get("/{path:path}")
async def html_landing() -> HTMLResponse:
    kwargs: dict = {"title": settings.SITE_TITLE}
    if settings.ROOT_PATH:
        kwargs["api_root_url"] = f"{settings.ROOT_PATH}/api"
        kwargs["api_path_strip"] = settings.ROOT_PATH
    return HTMLResponse(prebuilt_html(**kwargs).replace("</body>", f"{_BRAND_STYLE}</body>"))
