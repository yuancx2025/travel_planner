# tests/test_flight.py
import pytest
from tools.flight import search_flights_by_route

def test_flight_search_normalization(fake_aviationstack):
    flights = search_flights_by_route("RDU", "DCA", limit=5)
    assert isinstance(flights, list) and len(flights) >= 1
    f0 = flights[0]
    # required normalized fields
    for k in ["id", "source", "airline", "flight_number", "dep_airport", "arr_airport", "status", "raw"]:
        assert k in f0
    assert f0["source"] == "aviationstack"
    assert "price" in f0
    price = f0["price"]
    assert price["currency"] == "USD"
    assert price["amount"] > 0
    assert price["per"] == "ticket"
