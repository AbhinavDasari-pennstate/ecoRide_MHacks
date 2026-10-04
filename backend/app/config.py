"""Constants, model names and env settings. Every number shown to a user traces back to here."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# --- env (never print or log these) ---
DATABASE_URL = os.getenv("DATABASE_URL", "local")          # "local" = embedded pgserver (dev only)
DATABASE_URL_DIRECT = os.getenv("DATABASE_URL_DIRECT", "")
API_SERVICE_TOKEN = os.getenv("API_SERVICE_TOKEN", "")  # trusted server adapters only; never expose in browser JS
CORS_ORIGINS = [s.strip().rstrip("/") for s in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174").split(",") if s.strip()]
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"  # true for HTTPS deployments
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
MAPS_SERVER_KEY = os.getenv("MAPS_SERVER_KEY", "")
# Read at call time (config.PLANNER), so scripts can switch modes at runtime.
PLANNER = os.getenv("PLANNER", "gemini")                   # gemini (no key = fallback) | deterministic
EXPLAIN = os.getenv("EXPLAIN", "template")                  # template | gemini
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")  # fastest reliable Flash in an Oct 3 probe (3.7/3.8 were overloaded); 2.5 is closed to new keys
GEMINI_BACKUP_MODEL = os.getenv("GEMINI_BACKUP_MODEL", "gemini-3.5-flash-lite")  # used after a 429/5xx from GEMINI_MODEL

# --- voice agent and texting (scripts/setup_voice.py fills the ELEVENLABS_* ids) ---
API_TOKEN = os.getenv("API_TOKEN", "")                      # the voice scripts' name for API_SERVICE_TOKEN; either works
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")        # https tunnel to this server, e.g. an ngrok URL
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_AGENT_ID = os.getenv("ELEVENLABS_AGENT_ID", "")
ELEVENLABS_MCP_SERVER_ID = os.getenv("ELEVENLABS_MCP_SERVER_ID", "")
ELEVENLABS_PHONE_NUMBER_ID = os.getenv("ELEVENLABS_PHONE_NUMBER_ID", "")
ELEVENLABS_LLM = os.getenv("ELEVENLABS_LLM", "gemini-2.5-flash")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")  # empty = ElevenLabs' default voice
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")  # E.164, e.g. +17345550199
TWILIO_SMS_TEMPLATE = os.getenv("TWILIO_SMS_TEMPLATE", "")  # trial accounts only send templates, e.g. sms_appointment_reminders

# --- planner ---
PLANNER_TIMEOUT_S = 20
PLANNER_MAX_RETRIES = 2
PLANNER_MAX_TOOL_ROUNDS = 6   # function-call rounds per run, then Gemini must answer
GEMINI_TEMPERATURE = None     # Gemini 3.x deprecates temperature; None = the SDK omits it
GEMINI_THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "low")  # 3.x Flash defaults to medium (slow); never "minimal" (errors on 3.8 Flash)

# --- matching rules ---
DEST_RADIUS_MI = 0.5          # passengers' destination must be this close to the driver's
MIN_WINDOW_OVERLAP_MIN = 30   # fallback: the group's windows must share at least this much time
MAX_PICKUP_RADIUS_MI = 2.0    # fallback: passenger origin within this distance of the driver
OWN_CAR_SEATS = 4             # capacity when the driver brings their own car
AVAIL_BUFFER_MIN = 15         # vehicle must stay free this long after the rental ends
EV_RANGE_RESERVE = 0.20       # round trip must fit in (1 - reserve) * range
CO2_TIE_KG = 0.1              # vehicles within this much CO2 are a tie, cheaper one wins

# --- distance and time ---
ROAD_FACTOR = 1.3             # haversine * this when Maps is unavailable
AVG_SPEED_MPH = 25
STOP_BUFFER_HOURS = 1.0
RENTAL_INCREMENT_HOURS = 0.5

# --- emissions and prices (checked 2026-10-03, sources in SOURCES; a judge will ask) ---
GAS_KG_CO2_PER_GALLON = 8.887
BASELINE_KG_CO2_PER_MILE = 0.400
GRID_KG_CO2_PER_KWH = 0.440   # 970.617 lb/MWh * 0.45359237 / 1000, rounded; excludes transmission losses
OWN_CAR_MPG = 22.2            # EPA average on-road car, so an own car matches the baseline per mile
GAS_USD_PER_GALLON = 4.48     # ponytail: price snapshots, not live feeds
ELECTRICITY_USD_PER_KWH = 0.2305
# --- equivalents shown next to kg CO2 (EPA GHG Equivalencies Calculator, checked 2026-10-04) ---
TREE_SEEDLING_10YR_KG_CO2 = 60.0      # one urban tree seedling grown for 10 years: 0.060 t CO2
SMARTPHONE_CHARGE_KG_CO2 = 0.0124     # one smartphone charge: 1.24e-5 t CO2

TIMEZONE = "America/Detroit"
ANN_ARBOR = (42.2808, -83.7430)
# Demo destinations, matched by substring before geocoding so every "Meijer" trip lands on the same store
# (Meijer #64, OpenStreetMap building coords). ponytail: a dict, not a places table
KNOWN_PLACES = {"meijer": {"dest_name": "Meijer (Ann Arbor-Saline Rd)", "dest_place_id": None,
                           "dest_lat": 42.2394, "dest_lng": -83.7660}}

# name -> (unit, source). Shipped inside every `assumptions` object.
SOURCES = {
    "GAS_KG_CO2_PER_GALLON": ("kg CO2 per gallon of gasoline", "EPA, Greenhouse Gas Emissions from a Typical Passenger Vehicle (2026): 8,887 g CO2/gal"),
    "BASELINE_KG_CO2_PER_MILE": ("kg CO2 per mile", "EPA, Greenhouse Gas Emissions from a Typical Passenger Vehicle (2026): about 400 g CO2/mi"),
    "GRID_KG_CO2_PER_KWH": ("kg CO2 per kWh", "EPA eGRID2023 rev 2 (2025), RFCM (RFC Michigan) CO2 total output rate, 970.6 lb/MWh"),
    "OWN_CAR_MPG": ("mpg", "EPA (2026) average on-road gasoline vehicle, 22.2 mpg; assumed for drivers bringing their own car"),
    "GAS_USD_PER_GALLON": ("USD per gallon", "AAA Gas Prices, Michigan regular average, Oct 3 2026 ($4.48)"),
    "ELECTRICITY_USD_PER_KWH": ("USD per kWh", "EIA Electric Power Monthly Table 5.6.A (2026), Michigan residential, Jul 2026 (23.05 c/kWh)"),
    "AVG_SPEED_MPH": ("mph", "assumed in-town average for rental time"),
    "STOP_BUFFER_HOURS": ("hours", "assumed time parked at the destination"),
    "RENTAL_INCREMENT_HOURS": ("hours", "rental rounded up to this increment"),
    "EV_RANGE_RESERVE": ("fraction", "safety reserve kept on every vehicle's range"),
    "ROAD_FACTOR": ("ratio", "road miles per straight-line mile, used only when Maps is unavailable"),
    "TREE_SEEDLING_10YR_KG_CO2": ("kg CO2 per tree seedling grown for 10 years", "EPA Greenhouse Gas Equivalencies Calculator: 0.060 metric ton CO2 per urban tree planted and grown for 10 years"),
    "SMARTPHONE_CHARGE_KG_CO2": ("kg CO2 per smartphone charged", "EPA Greenhouse Gas Equivalencies Calculator: 1.24 x 10^-5 metric tons CO2 per smartphone charged"),
}

SOURCE_URLS = {
    "GAS_KG_CO2_PER_GALLON": "https://www.epa.gov/greenvehicles/greenhouse-gas-emissions-typical-passenger-vehicle",
    "BASELINE_KG_CO2_PER_MILE": "https://www.epa.gov/greenvehicles/greenhouse-gas-emissions-typical-passenger-vehicle",
    "OWN_CAR_MPG": "https://www.epa.gov/greenvehicles/greenhouse-gas-emissions-typical-passenger-vehicle",
    "GRID_KG_CO2_PER_KWH": "https://www.epa.gov/egrid/summary-data",
    "GAS_USD_PER_GALLON": "https://gasprices.aaa.com/?state=MI",
    "ELECTRICITY_USD_PER_KWH": "https://www.eia.gov/electricity/monthly/epm_table_grapher.php?t=epmt_5_6_a",
    "TREE_SEEDLING_10YR_KG_CO2": "https://www.epa.gov/energy/greenhouse-gas-equivalencies-calculator-calculations-and-references",
    "SMARTPHONE_CHARGE_KG_CO2": "https://www.epa.gov/energy/greenhouse-gas-equivalencies-calculator-calculations-and-references",
}
CHECKED_ON = {"TREE_SEEDLING_10YR_KG_CO2": "2026-10-04", "SMARTPHONE_CHARGE_KG_CO2": "2026-10-04"}   # everything else: 2026-10-03


def assumptions() -> dict:
    g = globals()
    return {name: {"value": g[name], "unit": unit, "source": src,
                   **({"url": SOURCE_URLS[name], "checked_on": CHECKED_ON.get(name, "2026-10-03")} if name in SOURCE_URLS else {})}
            for name, (unit, src) in SOURCES.items()}
