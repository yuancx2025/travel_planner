# tests/test_dining.py
from tools.dining import search_dining

def test_dining_search_normalization(fake_yelp):
    items = search_dining("ramen", 38.9, -77.04, limit=3)
    assert isinstance(items, list) and len(items) >= 1
    it0 = items[0]
    for k in ["id","source","name","category","address","coord","rating","review_count","url","raw"]:
        assert k in it0
    assert it0["source"] == "yelp"
    # Yelp gives price tier symbols - not numeric price
    assert "price_tier" in it0
