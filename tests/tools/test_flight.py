"""Unit tests for `tools.flight` Amadeus integration."""

from __future__ import annotations

from types import SimpleNamespace

from tools import flight


def _dummy_amadeus(data):
    return SimpleNamespace(
        shopping=SimpleNamespace(
            flight_offers_search=SimpleNamespace(get=lambda **kwargs: SimpleNamespace(data=data))
        )
    )


def test_search_flights_normalizes_offers(monkeypatch):
    sample = [
        {
            "itineraries": [{"duration": "PT5H30M"}],
            "price": {"total": "345.67", "currency": "USD"},
            "validatingAirlineCodes": ["AA"],
        }
    ]

    monkeypatch.setattr(flight, "amadeus", _dummy_amadeus(sample))

    results = flight.search_flights("RDU", "LAX", "2025-11-20", return_date="2025-11-27", adults=2)

    assert len(results) == 1
    offer = results[0]
    assert offer["carrier"] == "AA"
    assert offer["price"] == "345.67"
    assert offer["currency"] == "USD"
    assert offer["duration"] == "PT5H30M"
    assert offer["origin"] == "RDU"
    assert offer["return_date"] == "2025-11-27"


def test_search_flights_handles_response_error(monkeypatch):
    class DummyError(Exception):
        pass

    def _raise(**kwargs):  # pragma: no cover - exercised via call
        raise DummyError("boom")

    amadeus_mock = SimpleNamespace(
        shopping=SimpleNamespace(
            flight_offers_search=SimpleNamespace(get=_raise)
        )
    )

    monkeypatch.setattr(flight, "amadeus", amadeus_mock)
    monkeypatch.setattr(flight, "ResponseError", DummyError)

    results = flight.search_flights("RDU", "LAX", "2025-11-20")
    assert results == []
