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

import asyncio
from datetime import datetime
from typing import AsyncIterable

from fastapi import APIRouter
from fastui import AnyComponent, FastUI
from fastui import components as c
from fastui.events import GoToEvent
from sqlmodel import col
from starlette.responses import StreamingResponse

from amiss.db import Session
from amiss.frontend.util import (
    app_page,
    button_row,
    circuit_buttons,
    circuit_header,
    circuit_table,
    circuit_tabs,
)
from amiss.fsm import ConnectionStateMachine
from amiss.model import Circuit, Log

router = APIRouter()


@router.get("", response_model=FastUI, response_model_exclude_none=True)
async def circuits() -> list[AnyComponent]:
    """Redirect to active tab of circuits page."""
    return [c.FireEvent(event=GoToEvent(url="/circuits/active"))]


@router.get("/{id}/", response_model=FastUI, response_model_exclude_none=True)
def circuit_details(id: int) -> list[AnyComponent]:
    """Display circuit details."""
    with Session() as session:
        circuit = session.query(Circuit).filter(Circuit.id == id).one_or_none()  # type: ignore[arg-type]
    if circuit is None:
        return app_page(title=f"No circuit with id {id}.")
    return app_page(
        circuit_buttons(circuit),
        c.Heading(text="Circuit details", level=5),
        c.Details(data=circuit),
        c.Heading(text="SourceStp details", level=5),
        c.Details(data=circuit.sourceStp),
        c.Heading(text="DestStp details", level=5),
        c.Details(data=circuit.destStp),
        title=f"Circuit {circuit.description}",
    )


async def circuit_log_stream(id: int) -> AsyncIterable[str]:
    lines = []
    last_timestamp = datetime.fromtimestamp(0)
    while True:
        await asyncio.sleep(0.5)
        with Session() as session:
            messages = (
                session.query(Log.message, Log.timestamp)  # type: ignore[call-overload]
                .filter(Log.circuit_id == id)
                .filter(Log.timestamp > last_timestamp)
                .all()
            )
        for message, timestamp in messages:
            lines.append(c.Div(components=[c.Text(text=f"{timestamp.isoformat()} - {message}")]))
            last_timestamp = timestamp
        m = FastUI(root=lines)  # type: ignore[arg-type]
        yield f"data: {m.model_dump_json(by_alias=True, exclude_none=True)}\n\n"


@router.get("/{id}/log/sse")
async def circuit_log_sse(id: int) -> StreamingResponse:
    return StreamingResponse(circuit_log_stream(id), media_type="text/event-stream")


@router.get("/{id}/log", response_model=FastUI, response_model_exclude_none=True)
async def circuit_log(id: int) -> list[AnyComponent]:
    """Show streaming log for circuit with given id."""
    with Session() as session:
        circuit = session.query(Circuit).filter(Circuit.id == id).one_or_none()  # type: ignore[arg-type]
    if circuit is None:
        return app_page(title=f"No circuit with id {id}.")
    return app_page(
        button_row(
            [
                c.Button(
                    text="Back",
                    on_click=GoToEvent(url=f"/circuits/{id}/"),
                    class_name="+ ms-2",
                )
            ]
        ),
        circuit_header(circuit),
        c.Div(
            components=[
                c.ServerLoad(
                    path=f"/circuits/{id}/log/sse",
                    sse=True,
                    sse_retry=500,
                ),
            ],
            class_name="my-2 p-2 border rounded",
        ),
        title=f"Streaming logs {circuit.description}",
    )


@router.get("/all", response_model=FastUI, response_model_exclude_none=True)
def circuits_all() -> list[AnyComponent]:
    """Display overview of all circuits."""
    with Session() as session:
        circuits = session.query(Circuit).order_by(col(Circuit.id)).all()
    return app_page(
        *circuit_tabs(),
        circuit_table(circuits),
        title="All circuits",
    )


@router.get("/active", response_model=FastUI, response_model_exclude_none=True)
def circuits_active() -> list[AnyComponent]:
    """Display overview of active circuits."""
    with Session() as session:
        circuits = (
            session.query(Circuit)
            .filter(Circuit.state == ConnectionStateMachine.ConnectionActive.value)
            .order_by(col(Circuit.id))
            .all()
        )
    return app_page(
        *circuit_tabs(),
        circuit_table(circuits),
        title="Active circuits",
    )


@router.get("/attention", response_model=FastUI, response_model_exclude_none=True)
def circuits_attention() -> list[AnyComponent]:
    """Display overview of circuits that need attention."""
    with Session() as session:
        circuits = (
            session.query(Circuit)
            .filter(
                (Circuit.state != ConnectionStateMachine.ConnectionActive.value)
                & (Circuit.state != ConnectionStateMachine.ConnectionTerminating.value)
                & (Circuit.state != ConnectionStateMachine.ConnectionTerminated.value)
            )
            .order_by(col(Circuit.id))
            .all()
        )
    return app_page(
        *circuit_tabs(),
        circuit_table(circuits),
        title="Circuits that need attention",
    )
