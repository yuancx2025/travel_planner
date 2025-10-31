"""Tests for the RapidAPI car rental bridge."""

from __future__ import annotations

import pytest

from tools.car_rental import CarRentalError, CarRentalService, search_car_rentals


def _mock_results():
    return {
        "data": {
            "search_results": [
                {
                    "offer_id": "car-1",
                    "supplier_info": {"name": "Budget"},
                    "vehicle_info": {
                        "v_name": "Toyota Corolla",
                        "group": "compact",
                        "doors": 4,
                        "seats": 5,
                        "transmission": "automatic",
                        "air_conditioning": True,
                    },
                    "pricing_info": {"drive_away_price": "199.99", "currency": "USD"},
                    "route_info": {
                        "pickup": {"name": "RDU", "datetime": "2025-11-20T10:00:00"},
                        "dropoff": {"name": "RDU", "datetime": "2025-11-22T18:00:00"},
                    },
                },
                {
                    "offer_id": "car-2",
                    "supplier_info": {"name": "Avis"},
                    "vehicle_info": {"v_name": "SUV", "group": "suv"},
                    "pricing_info": {"drive_away_price": "220.50", "currency": "USD"},
                    "route_info": {
                        "pickup": {"name": "RDU"},
                        "dropoff": {"name": "RDU"},
                    },
                },
            ]
        }
    }


def test_search_car_rentals_normalizes_and_sorts(monkeypatch):
    monkeypatch.setenv("RAPIDAPI_KEY", "x" * 40)

    def _fake_http(self, url, params):  # pragma: no cover - exercised via call
        assert params["page"] == 1
        return _mock_results()

    monkeypatch.setattr(CarRentalService, "_http_get_json", _fake_http)

    cars = search_car_rentals(
        pickup_lat=35.8778,
        pickup_lon=-78.7875,
        pickup_date="2025-11-20",
        pickup_time="10:00",
        dropoff_lat=35.8778,
        dropoff_lon=-78.7875,
        dropoff_date="2025-11-22",
        dropoff_time="18:00",
        top_n=5,
    )

    assert [c["id"] for c in cars] == ["car-1", "car-2"]
    first = cars[0]
    assert first["price"]["amount"] == pytest.approx(199.99)
    assert first["price"]["duration_hours"] == pytest.approx(56.0)
    assert first["vehicle"]["name"] == "Toyota Corolla"


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    with pytest.raises(CarRentalError):
        CarRentalService(api_key="short")
