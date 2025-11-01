"""Offline tests for the Gemini-powered fuel price tool."""

from __future__ import annotations

import pytest

from tools import car_price


def test_get_fuel_prices_uses_cached_result(monkeypatch):
    sample = car_price.FuelPrices(
        location="Durham, NC",
        state="NC",
        regular=3.59,
        midgrade=3.89,
        premium=4.19,
        diesel=4.35,
    )

    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
    monkeypatch.setattr(car_price, "_cached_query", lambda location, bucket: sample)

    result = car_price.get_fuel_prices("durham, nc")

    assert result["state"] == "NC"
    assert result["currency"] == "USD"
    assert result["regular"] == pytest.approx(3.59)


def test_get_fuel_prices_missing_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with pytest.raises(car_price.FuelPriceError):
        car_price.get_fuel_prices("durham")
