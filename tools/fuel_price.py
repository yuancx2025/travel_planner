# tools/fuel_price.py
import os
import httpx
import re
from typing import Any, Dict

API_TOKEN = os.environ.get("COLLECTAPI_TOKEN")
BASE_URL = "https://api.collectapi.com/gasPrice"

class FuelPriceError(Exception):
    pass

def _coerce_numeric(value: Any) -> Any:
    """Attempt to convert CollectAPI stringified prices to floats."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[^0-9.]+", "", value)
        if cleaned:
            try:
                return float(cleaned)
            except ValueError:
                return value
    return value


def get_state_gas_prices(state_code: str) -> Dict[str, Any]:
    """
    Fetch fuel prices for a U.S. state via CollectAPI.
    Parameters:
      - state_code: two-letter US state code, e.g., "WA", "CA"
    Returns:
      A dict containing price fields for gasoline, midGrade, premium, diesel, unit, currency, etc.
    Raises:
      FuelPriceError if API returns failure or if token missing.
    Usage:
      get_state_gas_prices("WA")
    """
    if not API_TOKEN:
        raise FuelPriceError("Missing COLLECTAPI_TOKEN environment variable")

    url = f"{BASE_URL}/stateUsaPrice"
    headers = {
        "Authorization": API_TOKEN,
        "Content-Type": "application/json"
    }
    params = {"state": state_code.upper()}

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        raise FuelPriceError(f"HTTP request failed: {e}")

    if not data.get("success", False):
        raise FuelPriceError(f"API returned failure: {data}")

    result = data.get("result")
    if result is None:
        raise FuelPriceError(f"API did not return result field: {data}")

    if isinstance(result, dict):
        return {k: _coerce_numeric(v) for k, v in result.items()}
    if isinstance(result, list):
        return [{k: _coerce_numeric(v) for k, v in item.items()} for item in result]
    return result

if __name__ == "__main__":
    # simple test
    import sys
    if len(sys.argv) != 2:
        print("Usage: python fuel_price.py <STATE_CODE>")
        sys.exit(1)
    state = sys.argv[1]
    try:
        prices = get_state_gas_prices(state)
        print(f"Gas prices for {state}: {prices}")
    except FuelPriceError as e:
        print(f"Error: {e}")
        sys.exit(2)
