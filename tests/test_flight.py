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
    # Note: Aviationstack does NOT provide price; ensure we do NOT invent one
    assert "price" not in f0
