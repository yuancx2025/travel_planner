"""
Test for fuel_price.py (Google-based implementation).
"""
import os
import pytest
from tools.fuel_price import get_fuel_prices, get_state_gas_prices, FuelPriceError


# Skip if API key not available
pytestmark = pytest.mark.skipif(
    not os.environ.get("GOOGLE_MAPS_API_KEY"),
    reason="GOOGLE_MAPS_API_KEY not set"
)


def test_fuel_prices_by_city():
    """Test getting fuel prices by city name."""
    result = get_fuel_prices("San Francisco")
    
    assert result is not None
    assert "location" in result
    assert "state" in result
    assert "regular" in result
    assert "midgrade" in result
    assert "premium" in result
    assert "diesel" in result
    assert result["currency"] == "USD"
    assert result["unit"] == "per gallon"
    
    # Prices should be floats
    assert isinstance(result["regular"], float)
    assert isinstance(result["midgrade"], float)
    assert isinstance(result["premium"], float)
    assert isinstance(result["diesel"], float)
    
    # Prices should be reasonable (between $2 and $7 per gallon)
    assert 2.0 <= result["regular"] <= 7.0
    assert 2.0 <= result["midgrade"] <= 7.0
    assert 2.0 <= result["premium"] <= 7.0
    assert 2.0 <= result["diesel"] <= 7.0
    
    # Premium should be more expensive than regular
    assert result["premium"] > result["regular"]


def test_fuel_prices_different_states():
    """Test that different states have different prices."""
    ca_prices = get_fuel_prices("Los Angeles")
    tx_prices = get_fuel_prices("Houston")
    
    # California should generally be more expensive than Texas
    assert ca_prices["state"] == "CA"
    assert tx_prices["state"] == "TX"
    assert ca_prices["regular"] > tx_prices["regular"]


def test_fuel_prices_fallback_mode():
    """Test fallback mode (estimates) when search is disabled."""
    result = get_fuel_prices("Seattle", use_search=False)
    
    assert result is not None
    assert result["state"] == "WA"
    assert result["source"] == "estimate"
    assert isinstance(result["regular"], float)


def test_legacy_function():
    """Test legacy get_state_gas_prices function."""
    result = get_state_gas_prices("CA")
    
    assert result is not None
    assert result["state"] == "CA"
    assert "regular" in result
    assert isinstance(result["regular"], float)


def test_invalid_location():
    """Test error handling for invalid location."""
    with pytest.raises(FuelPriceError):
        get_fuel_prices("ThisCityDoesNotExist12345")


def test_fuel_prices_output_format():
    """Test that output format is consistent."""
    result = get_fuel_prices("New York")
    
    # Check all required fields exist
    required_fields = ["location", "state", "regular", "midgrade", "premium", 
                      "diesel", "currency", "unit", "source", "last_updated"]
    
    for field in required_fields:
        assert field in result, f"Missing field: {field}"


if __name__ == "__main__":
    # Run tests with verbose output
    pytest.main([__file__, "-v", "-s"])
