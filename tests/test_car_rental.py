# tests/test_car_rental.py
from tools.car_rental import search_car_rentals

def test_car_rental_returns_price_amount(fake_booking_cars):
    cars = search_car_rentals("DCA", "2025-11-20T10:00:00Z", "2025-11-22T18:00:00Z")
    assert isinstance(cars, list) and len(cars) >= 1
    c0 = cars[0]
    for k in ["id","source","supplier","vehicle","pickup","dropoff","price","raw"]:
        assert k in c0
    assert isinstance(c0["price"], dict)
    assert c0["price"]["currency"] == "USD"
    assert isinstance(c0["price"]["amount"], (int, float))
    assert c0["price"]["amount"] > 0
