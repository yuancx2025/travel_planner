"""Offline tests for the Gemini-powered fuel price tool."""

from __future__ import annotations

import pytest

from tools import car_price


def test_get_fuel_prices_uses_cached_result(monkeypatch):
    # Use updated CarAndFuelPrices model with car rental fields
    sample = car_price.CarAndFuelPrices(
        location="Durham, NC",
        state="NC",
        regular=3.59,
        midgrade=3.89,
        premium=4.19,
        diesel=4.35,
        economy_car_daily=45.0,
        compact_car_daily=55.0,
        midsize_car_daily=65.0,
        suv_daily=85.0,
    )

    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
    monkeypatch.setattr(car_price, "_cached_query", lambda location, bucket: sample)

    # Test legacy function filters out car rental data
    result = car_price.get_fuel_prices("durham, nc")

    assert result["state"] == "NC"
    assert result["currency"] == "USD"
    assert result["regular"] == pytest.approx(3.59)
    # Verify car rental fields are excluded
    assert "economy_car_daily" not in result
    assert "rental_unit" not in result


def test_get_fuel_prices_missing_key(monkeypatch):
    # Patch the module-level variable since it's read at import time
    monkeypatch.setattr(car_price, "GOOGLE_API_KEY", None)

    with pytest.raises(car_price.CarPriceError, match="Missing.*API_KEY"):
        car_price.get_fuel_prices("durham")


def test_get_car_and_fuel_prices_returns_combined_data(monkeypatch):
    """Test new combined function returns both fuel and car rental data."""
    sample = car_price.CarAndFuelPrices(
        location="San Francisco",
        state="CA",
        regular=4.8,
        midgrade=5.0,
        premium=5.2,
        diesel=5.1,
        economy_car_daily=50.0,
        compact_car_daily=60.0,
        midsize_car_daily=70.0,
        suv_daily=90.0,
    )

    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
    monkeypatch.setattr(car_price, "_cached_query", lambda location, bucket: sample)

    result = car_price.get_car_and_fuel_prices("San Francisco")

    # Verify fuel prices
    assert result["state"] == "CA"
    assert result["regular"] == pytest.approx(4.8)
    assert result["diesel"] == pytest.approx(5.1)

    # Verify car rental daily rates
    assert result["economy_car_daily"] == pytest.approx(50.0)
    assert result["compact_car_daily"] == pytest.approx(60.0)
    assert result["midsize_car_daily"] == pytest.approx(70.0)
    assert result["suv_daily"] == pytest.approx(90.0)

    # Verify metadata
    assert result["currency"] == "USD"
    assert result["fuel_unit"] == "per gallon"
    assert result["rental_unit"] == "per day"
    assert result["source"] == "google_search"
