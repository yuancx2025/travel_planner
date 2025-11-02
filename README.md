# Quick Start Guide

## 🚀 Running the Travel Planning Agent

### 1. Setup (One-time)
```bash
# Clone and install
cd 590_project
pip install -r requirements.txt

# Add API keys to .env
cat > .env << EOF
GOOGLE_MAPS_API_KEY=your_key_here
GOOGLE_API_KEY=your_gemini_key_here
AMADEUS_API_KEY=your_amadeus_key_here
AMADEUS_API_SECRET=your_amadeus_secret_here
EOF
```

### 2. Run Streamlit App (will implement later)
```bash
streamlit run app.py
```

### 3. Test Individual Tools
```python
# Weather
from tools.weather_v2 import get_weather
weather = get_weather("Paris", "2024-12-25", 3)

# Attractions
from tools.attractions import search_attractions
places = search_attractions("Tokyo", keyword="temple", limit=5)

# Dining
from tools.dining import search_restaurants
food = search_restaurants(35.6762, 139.6503, radius=2000, keyword="ramen")

# Hotels
from tools.hotels import search_hotels_by_city
hotels = search_hotels_by_city("LON", "2024-12-20", "2024-12-23")

# Car Rentals (NEW: requires lat/lng!)
from tools.car_rental import search_car_rentals
cars = search_car_rentals(
    pickup_lat=51.5074, pickup_lon=-0.1278,
    pickup_date="2024-12-20", pickup_time="10:00",
    dropoff_lat=51.5074, dropoff_lon=-0.1278,
    dropoff_date="2024-12-23", dropoff_time="10:00"
)

# Fuel Prices & Car Rental Rates (combined Gemini query)
from tools.car_price import get_car_and_fuel_prices
prices = get_car_and_fuel_prices("California")
# Returns: {location, state, regular, midgrade, premium, diesel, 
#           economy_car_daily, compact_car_daily, midsize_car_daily, suv_daily, ...}

# Legacy fuel-only function (backward compatible)
from tools.car_price import get_fuel_prices
fuel_only = get_fuel_prices("California")  # Filters out car rental data

# Distance Matrix
from tools.distance_matirx import get_distance_matrix
distances = get_distance_matrix(
    ["51.5074,-0.1278"], ["48.8566,2.3522"], mode="DRIVE"
)
```

### 4. Test ResearchAgent
```python
from agents.research_agent import ResearchAgent

agent = ResearchAgent()
state = {
    "destination_city": "Barcelona",
    "start_date": "2024-12-20",
    "travel_days": 4,
    "travelers": 2,
    "cuisine_pref": "tapas",
    "need_car_rental": "yes",
    "currency": "EUR",
    "temp_unit": "celsius"
}

results = agent.research(state)
# Returns: {weather, attractions, dining, hotels, car_rentals, fuel_prices, distances}
```

---

## 📋 Tool Signatures

### Weather
```python
get_weather(city: str, start_date: str, duration: int, units: str = "fahrenheit")
→ List[Dict]  # [{date, temp_max, temp_min, precip, conditions}, ...]
```

### Attractions
```python
search_attractions(city: str, keyword: str = "", limit: int = 10)
→ List[Dict]  # [{name, address, coord, rating, category}, ...]
```

### Dining
```python
search_restaurants(lat: float, lng: float, radius: int, keyword: str = "")
→ List[Dict]  # [{name, address, coord, rating, price_level}, ...]
```

### Hotels
```python
search_hotels_by_city(city_name: str, checkin_date: str, checkout_date: str, 
                      adults: int = 2, currency: str = "USD", limit: int = 5)
→ List[Dict]  # [{name, address, price, currency, rating}, ...]
```

### Car Rentals (⚠️ NEW INTERFACE)
```python
search_car_rentals(
    pickup_lat: float, pickup_lon: float,
    pickup_date: str,  # YYYY-MM-DD
    pickup_time: str,  # HH:MM
    dropoff_lat: float, dropoff_lon: float,
    dropoff_date: str, dropoff_time: str,
    currency: str = "USD", limit: int = 5
)
→ List[Dict]  # [{provider, vehicle_type, price, currency}, ...]
```

### Fuel Prices & Car Rental Rates (Combined)
```python
# New combined function (recommended)
get_car_and_fuel_prices(location: str)  # US state or city
→ Dict  # {location, state, regular, midgrade, premium, diesel,
        #  economy_car_daily, compact_car_daily, midsize_car_daily, suv_daily,
        #  currency, fuel_unit, rental_unit, source, last_updated}

# Legacy fuel-only function (backward compatible)
get_fuel_prices(location: str)  # Filters out car rental data
→ Dict  # {location, state, regular, midgrade, premium, diesel, ...}
```

### Distance Matrix
```python
get_distance_matrix(origins: List[str], destinations: List[str], mode: str = "DRIVE")
→ List[Dict]  # [{origin, destination, distance_km, duration_min}, ...]
```

## 🔑 API Key Quick Links

- **Google Maps**: https://console.cloud.google.com/apis/credentials
- **Gemini**: https://aistudio.google.com/app/apikey
- **Amadeus**: https://developers.amadeus.com/get-started/get-started-with-self-service-apis
