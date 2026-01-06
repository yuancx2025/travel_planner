# Travel Planner

## 🧭 System Overview

- **Streamlit UI (`streamlit_app.py`)** – provides the chat interface and calls the backend over HTTP using the session ID stored in `st.session_state`.
- **FastAPI backend (`api/main.py`)** – exposes `/sessions` and `/sessions/{id}/turns` endpoints, forwarding every turn to the runtime and returning updated state plus any human-in-the-loop interrupts.
- **LangGraph runtime (`workflows/runtime.py`)** – owns the long-lived `TravelPlannerState`, replays the compiled `travel_graph` workflow, and checkpoints progress with `MemorySaver` so steps can resume after an interrupt.
- **Agents & tools (`agents/`, `tools/`)** – specialized components that gather preferences (chat), research data (weather, attractions, dining, hotels, car + fuel, distances), craft itineraries, and estimate budgets.

## 🚀 Running the Travel Planning Agent

### 1. Setup (One-time)
```bash
# Clone and install deps
cd travel_planner-main
pip install -r requirements.txt

# Copy .env.example to .env and add your API keys
cp .env.example .env
# Then edit .env with your actual API keys

# Or create .env manually:
cat > .env <<'EOF'
GOOGLE_MAPS_API_KEY=your_key_here
GOOGLE_API_KEY=your_gemini_key_here
AMADEUS_API_KEY=your_amadeus_key_here
AMADEUS_API_SECRET=your_amadeus_secret_here
EOF
```

**Note:** The project now uses `python-dotenv` to automatically load environment variables from `.env`. All configuration is centralized in `config.py`.

### 2. Run the FastAPI backend
```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Expose required API keys as environment variables before launching the service.

### 3. Run the Streamlit front end
```bash
export TRAVEL_PLANNER_API_URL="http://localhost:8000"
streamlit run streamlit_app.py
```

### 4. Run the automated tests
```bash
pytest -v
```

### 5. Test Individual Tools
```python
# Weather
from tools.weather import get_weather
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

# Fuel Prices & Car Rental Rates (combined Gemini query)
from tools.car_price import get_car_and_fuel_prices
prices = get_car_and_fuel_prices("California")
# Returns: {location, state, regular, midgrade, premium, diesel, 
#           economy_car_daily, compact_car_daily, midsize_car_daily, suv_daily, ...}

# Legacy fuel-only function (backward compatible)
from tools.car_price import get_fuel_prices
fuel_only = get_fuel_prices("California")  # Filters out car rental data

# Distance Matrix
from tools.distance_matrix import get_distance_matrix
distances = get_distance_matrix(
    ["51.5074,-0.1278"], ["48.8566,2.3522"], mode="DRIVE"
)
```

### 5. Test ResearchAgent
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

## 🧪 End-to-End Flow

1. A user message submitted in Streamlit is POSTed to `/sessions/{id}/turns`.
2. `TravelPlannerRuntime` pushes the turn into the `travel_graph` state machine and waits for interrupts (human approval) or agent completions.
3. Research tasks fan out to the tool layer with retry/backoff, normalizing results into `weather`, `attractions`, `dining`, `hotels`, `car_rentals`, `fuel_prices`, and `distances` keys.
4. The itinerary and budget agents enrich the shared state, and final responses are rendered back through the chat UI.

When deploying to Cloud Run, set environment variables (`ENV`, `PORT`, `GOOGLE_PROJECT_ID`, `GOOGLE_LOCATION`, `GOOGLE_GENAI_MODEL`, `DATABASE_URL`, plus API keys) and configure CORS origins via `CORS_ORIGINS` to avoid wildcards in production.

## 🔑 API Key Quick Links

- **Google Maps**: https://console.cloud.google.com/apis/credentials
- **Gemini**: https://aistudio.google.com/app/apikey
- **Amadeus**: https://developers.amadeus.com/get-started/get-started-with-self-service-apis
