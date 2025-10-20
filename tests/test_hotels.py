# tests/test_hotels.py
from tools.hotels import search_hotels

def test_hotels_search_returns_price_amount(fake_booking_hotels):
    hotels = search_hotels("Washington, DC", "2025-11-20", "2025-11-22", guests=2)
    assert isinstance(hotels, list) and len(hotels) >= 1
    h0 = hotels[0]
    for k in ["id","source","name","address","city","country","stars","rating","review_count","price","url","raw"]:
        assert k in h0
    # Price should be a dict with amount and currency in USD
    assert isinstance(h0["price"], dict)
    assert h0["price"]["currency"] == "USD"
    assert isinstance(h0["price"]["amount"], (int, float))
    assert h0["price"]["amount"] > 0
