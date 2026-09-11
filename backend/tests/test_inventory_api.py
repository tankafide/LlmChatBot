from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from autoassist.db.models import Vehicle
from autoassist.inventory.records import normalize_text


@pytest.fixture
def seeded(client: TestClient) -> Iterator[tuple[TestClient, FastAPI, str, str]]:
    app = client.app
    dealerships = client.get("/dealerships").json()["items"]
    by_slug = {item["slug"]: item["id"] for item in dealerships}
    mia_id = by_slug["mia-motors"]
    lakeview_id = by_slug["lakeview-auto"]

    rows = [
        (
            "00000000-0000-0000-0000-000000000001",
            mia_id,
            "shared",
            "Toyota",
            "Camry",
            2022,
            2500000,
            "Sedan",
        ),
        (
            "00000000-0000-0000-0000-000000000002",
            mia_id,
            "punct",
            "Mercedes-Benz",
            "GLC 300",
            2023,
            4200050,
            "SUV/Crossover",
        ),
        (
            "00000000-0000-0000-0000-000000000003",
            mia_id,
            "unknowns",
            "Toyota",
            "Camry",
            2022,
            None,
            None,
        ),
        (
            "00000000-0000-0000-0000-000000000004",
            mia_id,
            "boundary",
            "Toyota",
            "Camry",
            2024,
            3000000,
            "Sedan",
        ),
        (
            "00000000-0000-0000-0000-000000000005",
            lakeview_id,
            "shared",
            "Toyota",
            "Camry",
            2022,
            2400000,
            "Sedan",
        ),
    ]
    with app.state.session_factory.begin() as session:
        for vehicle_id, dealership_id, source_id, make, model, year, price, body_type in rows:
            session.add(
                Vehicle(
                    id=vehicle_id,
                    dealership_id=dealership_id,
                    source_id=source_id,
                    make=make,
                    make_key=normalize_text(make),
                    model=model,
                    model_key=normalize_text(model),
                    year=year,
                    price_cents=price,
                    body_type=body_type,
                    body_type_key=None if body_type is None else normalize_text(body_type),
                )
            )
    yield client, app, mia_id, lakeview_id


def test_combined_filters_are_normalized_inclusive_and_exclude_nulls(
    seeded: tuple[TestClient, FastAPI, str, str],
) -> None:
    client, _, dealership_id, _ = seeded
    response = client.get(
        f"/dealerships/{dealership_id}/vehicles",
        params={
            "make": "  TOYOTA ",
            "model": "camry",
            "body_type": " sedan ",
            "year_min": 2022,
            "year_max": 2022,
            "price_min": "25000.00",
            "price_max": "25000.00",
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "source_id": "shared",
                "make": "Toyota",
                "model": "Camry",
                "year": 2022,
                "price": "25000.00",
                "body_type": "Sedan",
            }
        ],
        "next_after": None,
    }


def test_literal_punctuation_empty_results_and_nullable_serialization(
    seeded: tuple[TestClient, FastAPI, str, str],
) -> None:
    client, _, dealership_id, _ = seeded
    punctuation = client.get(
        f"/dealerships/{dealership_id}/vehicles",
        params={"make": "Mercedes-Benz", "body_type": "SUV/Crossover"},
    )
    assert [item["source_id"] for item in punctuation.json()["items"]] == ["punct"]

    all_inventory = client.get(f"/dealerships/{dealership_id}/vehicles").json()["items"]
    unknown = next(item for item in all_inventory if item["source_id"] == "unknowns")
    assert unknown["price"] is None
    assert unknown["body_type"] is None

    empty = client.get(f"/dealerships/{dealership_id}/vehicles", params={"make": "Does Not Exist"})
    assert empty.status_code == 200
    assert empty.json() == {"items": [], "next_after": None}


def test_stable_cursor_paging_and_dealership_isolation(
    seeded: tuple[TestClient, FastAPI, str, str],
) -> None:
    client, _, mia_id, lakeview_id = seeded
    first = client.get(f"/dealerships/{mia_id}/vehicles", params={"limit": 2}).json()
    assert [item["id"] for item in first["items"]] == [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    ]
    assert first["next_after"] == first["items"][-1]["id"]

    second = client.get(
        f"/dealerships/{mia_id}/vehicles",
        params={"limit": 2, "after": first["next_after"]},
    ).json()
    assert [item["id"] for item in second["items"]] == [
        "00000000-0000-0000-0000-000000000003",
        "00000000-0000-0000-0000-000000000004",
    ]
    assert second["next_after"] is None

    vehicle_id = first["items"][0]["id"]
    assert client.get(f"/dealerships/{mia_id}/vehicles/{vehicle_id}").status_code == 200
    cross_scope = client.get(f"/dealerships/{lakeview_id}/vehicles/{vehicle_id}")
    assert cross_scope.status_code == 404
    assert cross_scope.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    ("params", "expected_fragment"),
    [
        ({"year_min": 2025, "year_max": 2024}, "year_min"),
        ({"price_min": "2.001"}, "price"),
        ({"price_min": "92233720368547758.08"}, "price"),
        ({"price_min": "10.00", "price_max": "9.00"}, "price_min"),
        ({"limit": 101}, "limit"),
        ({"make": "   "}, "make"),
    ],
)
def test_invalid_filters_return_fastapi_validation_envelope(
    seeded: tuple[TestClient, FastAPI, str, str],
    params: dict[str, object],
    expected_fragment: str,
) -> None:
    client, _, dealership_id, _ = seeded
    response = client.get(f"/dealerships/{dealership_id}/vehicles", params=params)
    assert response.status_code == 422
    assert "detail" in response.json()
    assert expected_fragment in response.text


def test_missing_and_malformed_ids(seeded: tuple[TestClient, FastAPI, str, str]) -> None:
    client, _, dealership_id, _ = seeded
    missing = client.get(
        f"/dealerships/{dealership_id}/vehicles/{UUID('ffffffff-ffff-ffff-ffff-ffffffffffff')}"
    )
    assert missing.status_code == 404
    missing_dealership = client.get("/dealerships/ffffffff-ffff-ffff-ffff-ffffffffffff/vehicles")
    assert missing_dealership.status_code == 404
    assert client.get("/dealerships/not-a-uuid/vehicles").status_code == 422

    operation = client.app.openapi()["paths"]["/dealerships/{dealership_id}/vehicles"]["get"]
    assert {"200", "404", "422", "503"}.issubset(operation["responses"])


@pytest.mark.parametrize("result_count", [1, 100])
def test_response_query_count_is_constant(client: TestClient, result_count: int) -> None:
    app = client.app
    dealership_id = client.get("/dealerships").json()["items"][0]["id"]
    with app.state.session_factory.begin() as session:
        for index in range(result_count):
            session.add(
                Vehicle(
                    id=f"10000000-0000-0000-0000-{index:012d}",
                    dealership_id=dealership_id,
                    source_id=f"load-{index}",
                    make="Load",
                    make_key="load",
                    model="Test",
                    model_key="test",
                    year=2020,
                )
            )

    statements = 0

    def count_selects(*args: object, **kwargs: object) -> None:
        nonlocal statements
        statement = str(args[2])
        if statement.lstrip().upper().startswith("SELECT"):
            statements += 1

    event.listen(app.state.engine, "before_cursor_execute", count_selects)
    try:
        response = client.get(
            f"/dealerships/{dealership_id}/vehicles", params={"make": "Load", "limit": 100}
        )
    finally:
        event.remove(app.state.engine, "before_cursor_execute", count_selects)

    assert response.status_code == 200
    assert len(response.json()["items"]) == result_count
    assert statements == 2
