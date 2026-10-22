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

"""Tests for amiss.sources.providers: JSON->DTO mapping, the provider join and reservation links."""

import json
from functools import partial
from unittest.mock import patch

import pytest

from amiss.sources import aggregator, dds_topology
from amiss.sources.dds_topology import fetch_dds_nsas
from amiss.sources.providers import (
    DdsNsa,
    Upa,
    UpaReservation,
    build_providers,
    fetch_provider_reservations,
    fetch_providers,
    link_reservations,
    reservation_tab,
)
from amiss.sources.wfo import CircuitRow, StpSub

SUPA = "urn:ogf:network:surf.nl:2020:nsa:supa"
OPENNSA = "urn:ogf:network:es.net:2013:nsa:nsi-aggr-west"

PROVIDERS = {
    "providers": [
        {
            "nsaId": SUPA,
            "providerURL": "https://supa.surf.nl/provider",
            "networkIds": ["urn:ogf:network:surf.nl:2020:ana"],
        }
    ]
}

NSAS = [
    {
        "id": SUPA,
        "name": "SURF uPA",
        "providerUrl": "https://supa.surf.nl/provider",
        "networkIds": ["urn:ogf:network:surf.nl:2020:ana"],
        "roles": ["vnd.ogf.nsi.cs.v2.role.uPA"],
        "peersWith": ["urn:ogf:network:anaeng.global:2024:nsa:safnari"],
    }
]

RESERVATIONS = {
    "providerNSA": SUPA,
    "providerURL": "https://supa.surf.nl/provider",
    "reservations": [
        {
            "connectionId": "child-1",
            "globalReservationId": "urn:uuid:1",
            "description": "AMS-NYC",
            "requesterNSA": "urn:ogf:network:anaeng.global:2024:nsa:safnari",
            "reservationState": "ReserveStart",
            "provisionState": "Provisioned",
            "lifecycleState": "Created",
            "dataPlaneActive": True,
            "capacity": 1000,
            "sourceSTP": "urn:ogf:network:surf.nl:2020:ana:port-a?vlan=100",
            "destSTP": "urn:ogf:network:surf.nl:2020:ana:moxy-1?vlan=100",
        }
    ],
}


class TestFetch:
    def test_maps_providers(self):
        with patch.object(aggregator, "nsi_util_get_json", return_value=json.dumps(PROVIDERS).encode()):
            upas = fetch_providers()
        assert upas == [
            Upa(
                nsa_id=SUPA,
                provider_url="https://supa.surf.nl/provider",
                network_ids=["urn:ogf:network:surf.nl:2020:ana"],
            )
        ]

    def test_maps_dds_nsas(self):
        with patch.object(dds_topology, "get_dds_proxy_nsas", return_value=json.dumps(NSAS).encode()):
            nsas = fetch_dds_nsas()
        assert nsas == [
            DdsNsa(
                nsa_id=SUPA,
                name="SURF uPA",
                roles=["vnd.ogf.nsi.cs.v2.role.uPA"],
                peers_with=["urn:ogf:network:anaeng.global:2024:nsa:safnari"],
            )
        ]

    def test_maps_reservations_and_quotes_the_nsa_id(self):
        with patch.object(aggregator, "nsi_util_get_json", return_value=json.dumps(RESERVATIONS).encode()) as get:
            reservations = fetch_provider_reservations(SUPA)
        assert str(get.call_args.args[0]).endswith(
            "/providers/urn%3Aogf%3Anetwork%3Asurf.nl%3A2020%3Ansa%3Asupa/reservations"
        )
        assert reservations == [
            UpaReservation(
                connection_id="child-1",
                global_reservation_id="urn:uuid:1",
                reservation_state="ReserveStart",
                provision_state="Provisioned",
                lifecycle_state="Created",
                data_plane_active=True,
                capacity=1000,
                source_stp="urn:ogf:network:surf.nl:2020:ana:port-a?vlan=100",
                dest_stp="urn:ogf:network:surf.nl:2020:ana:moxy-1?vlan=100",
            )
        ]

    # Parsing failures are covered by the shared helpers' tests (fetch_agg_circuits, the dds_topology fetches).
    @pytest.mark.parametrize(
        ("fetch", "module", "patched"),
        [
            pytest.param(fetch_providers, aggregator, "nsi_util_get_json", id="providers"),
            pytest.param(
                partial(fetch_provider_reservations, SUPA), aggregator, "nsi_util_get_json", id="reservations"
            ),
            pytest.param(fetch_dds_nsas, dds_topology, "get_dds_proxy_nsas", id="nsas"),
        ],
    )
    def test_returns_none_on_failure(self, fetch, module, patched):
        with patch.object(module, patched, return_value=None):
            assert fetch() is None

    def test_skips_items_without_an_id(self):
        body = {"providers": [{"providerURL": "x"}, {"nsaId": SUPA}]}
        with patch.object(aggregator, "nsi_util_get_json", return_value=json.dumps(body).encode()):
            assert [upa.nsa_id for upa in fetch_providers()] == [SUPA]


class TestBuildProviders:
    def test_joins_dds_detail_and_sorts_by_name(self):
        upas = [Upa(nsa_id=SUPA, network_ids=["urn:ogf:network:a", "urn:ogf:network:b"]), Upa(nsa_id=OPENNSA)]
        nsas = [DdsNsa(nsa_id=SUPA, name="SURF uPA", roles=["r1", "r2"]), DdsNsa(nsa_id=OPENNSA, name="ESnet")]
        result = build_providers(upas, nsas)
        assert [row.name for row in result.rows] == ["ESnet", "SURF uPA"]
        surf = result.rows[1]
        assert surf.roles == "r1, r2" and surf.networks == "a, b" and surf.short_nsa_id == "surf.nl:2020:nsa:supa"

    @pytest.mark.parametrize(
        "nsas",
        [pytest.param(None, id="dds-down"), pytest.param([], id="not-in-dds")],
    )
    def test_rows_without_dds_detail_are_named_by_id(self, nsas):
        result = build_providers([Upa(nsa_id=SUPA)], nsas)
        assert result.error is None
        assert [(row.name, row.roles) for row in result.rows] == [(SUPA, None)]

    def test_aggregator_down_is_an_error(self):
        result = build_providers(None, [])
        assert result.rows == [] and "aggregator proxy" in result.error


def _reservation(gri="urn:uuid:1", source="urn:ogf:network:x:port-a?vlan=100", dest=None):
    return UpaReservation(connection_id="child-1", global_reservation_id=gri, source_stp=source, dest_stp=dest)


# The parent connection id differs from the uPA's child id: only the global reservation id is shared.
WFO = [
    CircuitRow(subscription_id="sub-1", connection_id="parent-1", global_reservation_id="urn:uuid:1"),
    CircuitRow(subscription_id="sub-2", connection_id="parent-2"),  # no gri: never matches a missing one
]
STPS = [StpSub(subscription_id="stp-a", stp_id="urn:ogf:network:x:port-a")]


class TestLinkReservations:
    @pytest.mark.parametrize(
        ("gri", "expected"),
        [
            pytest.param("urn:uuid:1", "sub-1", id="gri-to-wfo"),
            pytest.param("urn:uuid:other", None, id="foreign-or-retried-unlinked"),
            pytest.param(None, None, id="no-gri-unlinked"),
        ],
    )
    def test_circuit_link(self, gri, expected):
        [row] = link_reservations([_reservation(gri)], WFO, STPS)
        assert row.subscription_id == expected

    def test_two_reservations_of_one_circuit_both_link(self):
        """A path entering the same uPA twice leaves it two child connections with the circuit's gri."""
        rows = link_reservations([_reservation(), _reservation()], WFO, STPS)
        assert [row.subscription_id for row in rows] == ["sub-1", "sub-1"]

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            pytest.param("urn:ogf:network:x:port-a?vlan=100", "stp-a", id="vlan-stripped"),
            pytest.param("x:port-a", "stp-a", id="no-urn-prefix"),
            pytest.param("urn:ogf:network:x:port-b", None, id="no-subscription"),
            pytest.param(None, None, id="no-stp"),
        ],
    )
    def test_stp_link(self, source, expected):
        [row] = link_reservations([_reservation(source=source, dest=source)], WFO, STPS)
        assert row.source_stp_subscription_id == expected and row.dest_stp_subscription_id == expected

    def test_stps_are_shortened_for_the_table(self):
        [row] = link_reservations([_reservation(dest="urn:ogf:network:x:port-b")], WFO, STPS)
        assert (row.source, row.dest) == ("x:port-a (vlan 100)", "x:port-b")
        assert row.source_stp == "urn:ogf:network:x:port-a?vlan=100"

    def test_wfo_down_leaves_links_empty(self):
        [row] = link_reservations([_reservation()], None, None)
        assert (row.connection_id, row.subscription_id, row.source_stp_subscription_id) == ("child-1", None, None)


@pytest.mark.parametrize(
    ("lifecycle", "expected"),
    [
        pytest.param("Created", "active", id="created"),
        pytest.param("Terminating", "terminated", id="terminating"),
        pytest.param("Terminated", "terminated", id="terminated"),
        pytest.param("Failed", None, id="failed"),
        pytest.param("PassedEndTime", None, id="passed-end-time"),
        pytest.param(None, None, id="unknown"),
    ],
)
def test_reservation_tab(lifecycle, expected):
    assert reservation_tab(UpaReservation(connection_id="c", lifecycle_state=lifecycle)) == expected
