# Testing Guide

## Prerequisites

### 1. Python Environment
```bash
python --version  # Should be 3.11+
pip install -r requirements.txt
```

### 2. Environment Variables
Create `.env` file in project root:

```bash
# Google Maps APIs (required for most tools)
GOOGLE_MAPS_API_KEY=your_google_maps_api_key_here

# Google Gemini (required for agents)
GOOGLE_API_KEY=your_gemini_api_key_here

# RapidAPI (required for car rentals)
RAPIDAPI_KEY=your_rapidapi_key_here

# Amadeus (required for hotels)
AMADEUS_API_KEY=your_amadeus_api_key_here
AMADEUS_API_SECRET=your_amadeus_api_secret_here
```

**How to get API keys:**
- **Google Maps**: https://console.cloud.google.com/ → Enable Maps, Places, Routes APIs
- **Google Gemini**: https://aistudio.google.com/app/apikey
- **RapidAPI**: https://rapidapi.com/ → Subscribe to "booking-com-api5"
- **Amadeus**: https://developers.amadeus.com/ → Create app

---

## Unit Tests (Tool-by-Tool)

### Test 1: Weather
```bash
pytest tests/test_weather.py -v
```
**Expected**: Weather forecasts for test cities with temp/precip data

**Manual test:**
```python
from tools.weather_v2 import get_weather
result = get_weather("San Francisco", "2024-12-20", 3, "fahrenheit")
print(result)
```

---

### Test 2: Attractions
```bash
pytest tests/test_attractions.py -v
```
**Expected**: List of attractions with names, addresses, coordinates

**Manual test:**
```python
from tools.attractions import search_attractions
result = search_attractions("Paris", keyword="museum", limit=5)
print(result)
```

---

### Test 3: Dining
```bash
pytest tests/test_dining.py -v
```
**Expected**: Restaurants near coordinates with ratings

**Manual test:**
```python
from tools.dining import search_restaurants
result = search_restaurants(37.7749, -122.4194, radius=3000, keyword="italian")
print(result)
```

---

### Test 4: Hotels
```bash
pytest tests/test_hotels.py -v
```
**Expected**: Hotels with prices, addresses, ratings

**Manual test:**
```python
from tools.hotels import search_hotels_by_city
result = search_hotels_by_city("New York", "2024-12-20", "2024-12-23", adults=2, limit=3)
print(result)
```

---

### Test 5: Car Rentals
```bash
pytest tests/test_car_rental.py -v
```
**Expected**: Car rental options with prices, vehicle types

**Manual test:**
```python
from tools.car_rental import search_car_rentals
result = search_car_rentals(
    pickup_lat=37.7749, pickup_lon=-122.4194,
    pickup_date="2024-12-20", pickup_time="10:00",
    dropoff_lat=37.7749, dropoff_lon=-122.4194,
    dropoff_date="2024-12-23", dropoff_time="10:00",
    limit=5
)
print(result)
```

---

### Test 6: Fuel Prices
```bash
pytest tests/test_fuel_price.py -v
```
**Expected**: State-based fuel price estimates

**Manual test:**
```python
from tools.fuel_price import get_fuel_prices
result = get_fuel_prices("Los Angeles")
print(result)  # Should show regular/premium/diesel estimates
```

---

### Test 7: Distance Matrix
```bash
pytest tests/test_distance.py -v  # If exists
```

**Manual test:**
```python
from tools.distance_matirx import get_distance_matrix
origins = ["37.7749,-122.4194"]  # SF
destinations = ["34.0522,-118.2437", "36.7783,-119.4179"]  # LA, Fresno
result = get_distance_matrix(origins, destinations, mode="DRIVE")
print(result)
```

---

## Integration Tests (Agent Workflows)

### Test 8: ResearchAgent
```bash
pytest tests/test_agent_workflow.py -v
```

**Manual test:**
```python
from agents.research_agent import ResearchAgent

agent = ResearchAgent()
state = {
    "destination_city": "Miami",
    "start_date": "2024-12-25",
    "travel_days": 3,
    "travelers": 2,
    "cuisine_pref": "seafood",
    "need_car_rental": "yes",
    "currency": "USD",
    "temp_unit": "fahrenheit"
}

results = agent.research(state)
print(f"Weather: {len(results.get('weather', []))} forecasts")
print(f"Attractions: {len(results.get('attractions', []))} items")
print(f"Dining: {len(results.get('dining', []))} restaurants")
print(f"Hotels: {len(results.get('hotels', []))} options")
print(f"Car rentals: {len(results.get('car_rentals', []))} vehicles")
print(f"Fuel prices: {results.get('fuel_prices')}")
```

---

### Test 9: Full Agent Stack (ChatAgent → PlannerAgent)
```bash
pytest tests/test_chatter_agent_all.py -v
```

**Manual test (requires all APIs):**
```python
from agents.planner_agent import PlannerAgent

planner = PlannerAgent()
user_query = "I want to visit Tokyo for 5 days starting Dec 20. I love sushi and need a car."

plan = planner.plan(user_query)
print(plan)
```

---

## Troubleshooting

### Common Issues

**1. `httpx.ConnectError: Connection refused`**
- **Cause**: No internet or API endpoint down
- **Fix**: Check network, retry in a few minutes

**2. `KeyError: 'GOOGLE_MAPS_API_KEY'`**
- **Cause**: Missing environment variable
- **Fix**: Ensure `.env` is loaded (`python-dotenv`)

**3. `401 Unauthorized` or `403 Forbidden`**
- **Cause**: Invalid API key or exceeded quota
- **Fix**: Verify key is correct, check billing/quota in API console

**4. `car_rental.py` returns empty list**
- **Cause**: No rentals available for lat/lng or dates
- **Fix**: Try major cities (NYC, LA, SF) with future dates

**5. `hotels.py` returns no results**
- **Cause**: Amadeus city code mismatch
- **Fix**: Use exact city names ("New York", "Los Angeles", not abbreviations)

**6. Fuel prices show "No data"**
- **Cause**: Only US states supported
- **Fix**: Use US cities (e.g., "Dallas", "Seattle")

---

## Test Coverage Report
```bash
pytest --cov=tools --cov=agents tests/ --cov-report=html
open htmlcov/index.html
```

---

## Performance Benchmarks

Run performance tests:
```bash
pytest tests/ --durations=10  # Show 10 slowest tests
```

**Expected timing:**
- Weather: <1s
- Attractions: 1-2s
- Dining: 1-2s
- Hotels: 2-3s (Amadeus OAuth)
- Car rentals: 2-4s (RapidAPI)
- Fuel prices: <0.5s (local estimates)
- Distance matrix: 1-2s

---

## CI/CD Integration

### GitHub Actions Example
```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: pytest tests/ --maxfail=3
    env:
      GOOGLE_MAPS_API_KEY: ${{ secrets.GOOGLE_MAPS_API_KEY }}
      GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
      RAPIDAPI_KEY: ${{ secrets.RAPIDAPI_KEY }}
      AMADEUS_API_KEY: ${{ secrets.AMADEUS_API_KEY }}
      AMADEUS_API_SECRET: ${{ secrets.AMADEUS_API_SECRET }}
```

---

## Quick Validation Checklist

Before committing changes:
- [ ] All unit tests pass: `pytest tests/test_*.py`
- [ ] No syntax errors: `python -m py_compile tools/*.py agents/*.py`
- [ ] Code formatted: `black tools/ agents/`
- [ ] No linting errors: `ruff check tools/ agents/`
- [ ] Manual smoke test of updated tool
- [ ] Environment variables documented in `.env.example`

---

## API Rate Limits & Costs

| API | Free Tier | Rate Limit | Cost Beyond Free |
|-----|-----------|------------|------------------|
| Google Maps | $200/month credit | 50 req/s | ~$0.005/req |
| Google Gemini | 60 req/min | 60 RPM | Free (beta) |
| RapidAPI (Booking) | 500 req/month | 10 req/s | $0.01/req |
| Amadeus | 2000 req/month | 10 req/s | Pay-as-you-go |

**Cost-saving tips:**
- Cache API responses locally
- Use smaller result limits (`limit=5` vs `limit=20`)
- Batch distance matrix calls
- Only call fuel_price once per trip (state-level data)
