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
from fastui import AnyComponent
from fastui import components as c
from fastui.components.display import DisplayLookup
from fastui.events import GoToEvent

from amiss.model import SDP, STP, Circuit, Segment
from amiss.settings import settings

# do not know why, but otherwise FastUI will complain
c.Link.model_rebuild()


def app_page(*components: AnyComponent, title: str | None = None) -> list[AnyComponent]:
    return [
        c.PageTitle(text=f"AMISS — {title}" if title else "AMISS"),
        c.Navbar(
            title=settings.SITE_TITLE,
            title_event=GoToEvent(url="/"),
            start_links=[
                c.Link(
                    components=[c.Text(text="Circuits")],
                    on_click=GoToEvent(url="/circuits/active"),
                    active="startswith:/circuits",
                ),
                c.Link(
                    components=[c.Text(text="STP")],
                    on_click=GoToEvent(url="/stp/active"),
                    active="startswith:/stp",
                ),
                c.Link(
                    components=[c.Text(text="SDP")],
                    on_click=GoToEvent(url="/sdp/active"),
                    active="startswith:/sdp",
                ),
                c.Link(
                    components=[c.Text(text="Spectrum")],
                    on_click=GoToEvent(url="/spectrum/active"),
                    active="startswith:/spectrum",
                ),
                # c.Link(
                #     components=[c.Text(text="Auth")],
                #     on_click=GoToEvent(url="/auth/login/password"),
                #     active="startswith:/auth",
                # ),
                # c.Link(
                #     components=[c.Text(text="Forms")],
                #     on_click=GoToEvent(url="/forms/login"),
                #     active="startswith:/forms",
                # ),
            ],
        ),
        c.Page(
            components=[
                *((c.Heading(text=title),) if title else ()),
                *components,
                amiss_logo(),
            ],
        ),
        c.Footer(
            extra_text="AMISS",
            links=[
                c.Link(
                    components=[c.Text(text="Github")],
                    on_click=GoToEvent(url="https://github.com/workfloworchestrator/nsi-mgmt-info/"),
                ),
            ],
        ),
    ]


def amiss_logo() -> AnyComponent:
    return c.Div(
        components=[
            c.Image(
                # src='https://avatars.githubusercontent.com/u/110818415',
                src=f"{settings.ROOT_PATH}/static/ANA-logo-scaled-ab3.png",
                alt="ANA footer Logo",
                width=800,
                height=58,
                loading="lazy",
                referrer_policy="no-referrer",
            )
        ],
        class_name="+ d-flex justify-content-center",
    )


def circuit_table(circuits: list[Circuit]) -> c.Table:
    return c.Table(
        data_model=Circuit,
        data=circuits,
        columns=[
            DisplayLookup(field="id", on_click=GoToEvent(url="/circuits/{id}/")),
            DisplayLookup(field="description"),
            DisplayLookup(field="startTime"),
            DisplayLookup(field="endTime"),
            DisplayLookup(field="sourceStp"),
            DisplayLookup(field="sourceVlan"),
            DisplayLookup(field="destStp"),
            DisplayLookup(field="destVlan"),
            DisplayLookup(field="bandwidth"),
            DisplayLookup(field="state"),
        ],
        class_name="+ small",
    )


def stp_table(stps: list[STP]) -> c.Table:
    return c.Table(
        data_model=STP,
        data=stps,
        columns=[
            DisplayLookup(field="id", on_click=GoToEvent(url="/stp/{id}/")),
            DisplayLookup(field="stpId"),
            DisplayLookup(field="vlanRange"),
            DisplayLookup(field="description"),
            DisplayLookup(field="active"),
        ],
        class_name="+ small",
    )


def sdp_table(sdps: list[SDP]) -> c.Table:
    return c.Table(
        data_model=SDP,
        data=sdps,
        columns=[
            DisplayLookup(field="id", on_click=GoToEvent(url="/sdp/{id}/")),
            DisplayLookup(field="stpAId"),
            DisplayLookup(field="stpZId"),
            DisplayLookup(field="vlanRange"),
            DisplayLookup(field="description"),
            DisplayLookup(field="active"),
        ],
        class_name="+ small",
    )


def spectrum_table(sdps: list[SDP]) -> c.Table:
    return c.Table(
        data_model=SDP,
        data=sdps,
        columns=[
            DisplayLookup(field="id", on_click=GoToEvent(url="/spectrum/{id}/")),
            # DisplayLookup(field="stpAId"),
            # DisplayLookup(field="stpZId"),
            DisplayLookup(field="description"),
            DisplayLookup(field="vlanRange"),
            # DisplayLookup(field="active"),
        ],
        class_name="+ small",
    )


def segment_table(segments: list[Segment]) -> c.Table:
    return c.Table(
        data_model=Segment,
        data=segments,
        columns=[
            DisplayLookup(field="id", on_click=GoToEvent(url="/segment/{id}/")),  # ARNOTODO
            DisplayLookup(field="circuit_id"),
            DisplayLookup(field="order"),
            DisplayLookup(field="sourceStp"),
            DisplayLookup(field="destStp"),
            DisplayLookup(field="capacity"),
        ],
        class_name="+ small",
    )


def circuit_tabs() -> list[AnyComponent]:
    return [
        c.LinkList(
            links=[
                c.Link(
                    components=[c.Text(text="Active")],
                    on_click=GoToEvent(url="/circuits/active"),
                    active="startswith:/circuits/active",
                ),
                c.Link(
                    components=[c.Text(text="Attention")],
                    on_click=GoToEvent(url="/circuits/attention"),
                    active="startswith:/circuits/attention",
                ),
                c.Link(
                    components=[c.Text(text="All")],
                    on_click=GoToEvent(url="/circuits/all"),
                    active="startswith:/circuits/all",
                ),
            ],
            mode="tabs",
            class_name="+ mb-4",
        ),
    ]


def circuit_header(circuit: Circuit) -> c.Div:
    return c.Div(
        class_name="+ container fw-bold fs-6",
        components=[
            c.Div(
                class_name="+ row",
                components=[
                    c.Div(class_name="+ col-md-2", components=[c.Text(text="Id:")]),
                    c.Div(class_name="+ col-md-10", components=[c.Text(text=str(circuit.id))]),
                ],
            ),
            c.Div(
                class_name="+ row",
                components=[
                    c.Div(class_name="+ col-md-2", components=[c.Text(text="Description:")]),
                    c.Div(class_name="+ col-md-10", components=[c.Text(text=circuit.description)]),
                ],
            ),
            c.Div(
                class_name="+ row",
                components=[
                    c.Div(class_name="+ col-md-2", components=[c.Text(text="Connection ID:")]),
                    c.Div(class_name="+ col-md-10", components=[c.Text(text=str(circuit.connectionId))]),
                ],
            ),
            # add some margin at bottom size 3
            c.Div(class_name="+ row mb-3", components=[]),
        ],
    )


def button_row(buttons: list[c.Button]) -> c.Div:
    # gap: between elements, py: padding y-axis
    return c.Div(components=buttons, class_name="d-flex flex-row gap-1 py-3")


def circuit_buttons(circuit: Circuit) -> c.Div:
    return button_row(
        [
            c.Button(
                text="Back",
                on_click=GoToEvent(url="/circuits"),
                class_name="+ ms-2",
            ),
            c.Button(
                text="Log",
                on_click=GoToEvent(url=f"/circuits/{circuit.id}/log"),
                class_name="+ ms-2",
            ),
        ]
    )
