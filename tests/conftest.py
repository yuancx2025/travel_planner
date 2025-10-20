# tests/conftest.py
import os
import json
import types
import pytest

# ---- Generic fake HTTP response ----
class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.request = types.SimpleNamespace()
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not (200 <= self.status_code < 300):
            raise AssertionError(f"HTTP {self.status_code}: {self._payload}")

# ---- Helpers: monkeypatch each module’s _request or httpx.Client ----
@pytest.fixture
def fake_aviationstack(monkeypatch):
    # tools.flight uses _request(method,url,**kw)
    import tools.flight as flight

    sample = {
        "data": [
            {
                "airline": {"name": "American Airlines"},
                "flight": {"iata": "AA217", "number": "217"},
                "departure": {"iata": "RDU", "scheduled": "2025-11-20T12:05:00-05:00"},
                "arrival":   {"iata": "DCA", "scheduled": "2025-11-20T13:10:00-05:00"},
                "flight_status": "scheduled",
            }
        ]
    }

    def _fake_request(method, url, **kw):
        return FakeResponse(sample, 200)

    monkeypatch.setattr(flight, "_request", _fake_request)
    return sample

@pytest.fixture
def fake_yelp(monkeypatch):
    import tools.dining as dining

    sample = {
        "businesses": [
            {
                "id": "abc123",
                "name": "Ramen Place",
                "coordinates": {"latitude": 38.9, "longitude": -77.04},
                "location": {"address1": "123 Noodle St", "city": "Washington", "state": "DC", "zip_code": "20001"},
                "rating": 4.3,
                "review_count": 112,
                "display_phone": "(202) 555-1234",
                "url": "https://www.yelp.com/biz/abc123",
                "price": "$$",
                "is_closed": False,
            }
        ]
    }

    def _fake_request(method, url, **kw):
        return FakeResponse(sample, 200)

    monkeypatch.setattr(dining, "_request", _fake_request)
    return sample

@pytest.fixture
def fake_booking_hotels(monkeypatch):
    import tools.hotels as hotels

    sample = {
        "result": [
            {
                "hotel_id": 98765,
                "name": "Downtown Inn",
                "address": "1 Main St",
                "city": "Washington",
                "country": "US",
                "class": 3.0,
                "review_score": 8.4,
                "review_nr": 201,
                "currency": "USD",
                "price": 159.99,
                "url": "https://booking.example/h/98765",
            }
        ]
    }

    def _fake_request(method, url, **kw):
        return FakeResponse(sample, 200)

    monkeypatch.setattr(hotels, "_request", _fake_request)
    return sample

@pytest.fixture
def fake_booking_cars(monkeypatch):
    import tools.car_rental as cars

    sample = {
        "result": [
            {
                "offer_id": "car-offer-1",
                "vehicle": {"type": "economy", "doors": 4, "seats": 5, "transmission": "automatic", "air_conditioning": True},
                "supplier": {"name": "Budget"},
                "pickup": {"name": "DCA Terminal"},
                "dropoff": {"name": "DCA Terminal"},
                "currency": "USD",
                "price": 96.50,
                "free_cancellation": True,
            }
        ]
    }

    def _fake_request(method, url, **kw):
        return FakeResponse(sample, 200)

    monkeypatch.setattr(cars, "_request", _fake_request)
    return sample

@pytest.fixture
def fake_collectapi_fuel(monkeypatch):
    # tools.fuel_price uses httpx.Client(...).get -> Response
    import tools.fuel_price as fuel

    class FakeClient:
        def __init__(self, timeout=10):
            pass
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): pass
        def get(self, url, headers=None, params=None):
            # This payload shape mirrors a common CollectAPI pattern:
            # { success: true, result: { state: "VA", gasoline: 3.459, diesel: 4.099, unit: "USD/gal" } }
            resp = {
                "success": True,
                "result": {"state": "VA", "gasoline": 3.459, "diesel": 4.099, "unit": "USD/gal"}
            }
            return FakeResponse(resp, 200)

    monkeypatch.setattr(fuel, "httpx", types.SimpleNamespace(Client=FakeClient))
    return {"gasoline": 3.459, "diesel": 4.099, "unit": "USD/gal"}

# ---- A marker to enable optional live tests ----
def pytest_configure(config):
    config.addinivalue_line("markers", "live: mark test as requiring live API keys")
