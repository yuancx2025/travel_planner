# tests/test_fuel_price.py
from tools.fuel_price import get_state_gas_prices

def test_fuel_price_state_result(fake_collectapi_fuel):
    res = get_state_gas_prices("VA")
    # The wrapper returns API "result" directly
    assert isinstance(res, dict)
    # gas values might be numeric per CollectAPI; assert presence
    assert "gasoline" in res and "diesel" in res
    assert isinstance(res["gasoline"], (int, float))
    assert res["gasoline"] > 0
