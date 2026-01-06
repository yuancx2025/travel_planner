"""Unit tests for `tools.hotels` using mocked Amadeus client."""

from __future__ import annotations

from types import SimpleNamespace

from tools import hotels


def _make_amadeus(hotel_rows, offer_rows):
    class _HotelsByCity:
        def get(self, *, cityCode):  # pragma: no cover - exercised via call
            return SimpleNamespace(data=hotel_rows)

    class _HotelOffers:
        def get(self, **params):  # pragma: no cover - exercised via call
            return SimpleNamespace(data=offer_rows)

    return SimpleNamespace(
        reference_data=SimpleNamespace(
            locations=SimpleNamespace(
                hotels=SimpleNamespace(by_city=_HotelsByCity())
            )
        ),
        shopping=SimpleNamespace(
            hotel_offers_search=_HotelOffers()
        ),
    )


def test_search_hotels_returns_normalized_results(monkeypatch):
    hotel_rows = [{"hotelId": "H1"}]
    offer_rows = [
        {
            "hotel": {
                "hotelId": "H1",
                "name": "Downtown Inn",
                "address": {"lines": ["123 Main St"]},
                "rating": "4",
            },
            "offers": [{"price": {"total": "450.00", "currency": "USD"}}],
        }
    ]

    monkeypatch.setattr(hotels, "amadeus", _make_amadeus(hotel_rows, offer_rows))

    results = hotels.search_hotels_by_city("Durham", "2025-11-01", "2025-11-03", adults=2, limit=1)

    assert len(results) == 1
    first = results[0]
    assert first["hotel_id"] == "H1"
    assert first["name"] == "Downtown Inn"
    assert first["address"] == "123 Main St"
    assert first["price"] == "450.00"
    assert first["currency"] == "USD"
    assert first["rating"] == "4"
    assert first["source"] == "amadeus"


def test_search_hotels_unknown_city_returns_empty(monkeypatch):
    # Ensure ValueError path is handled gracefully
    results = hotels.search_hotels_by_city("Atlantis", "2025-11-01", "2025-11-03")
    assert results == []
