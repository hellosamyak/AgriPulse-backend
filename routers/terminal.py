from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
import requests
from google import genai
import os
from dotenv import load_dotenv
import datetime
import json
import statistics

load_dotenv()

router = APIRouter(prefix="/terminal", tags=["Agri Terminal"])

DATA_GOV_API_KEY = os.getenv("DATA_GOV_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize Gemini client
client = genai.Client(api_key=GEMINI_API_KEY)


@router.get("/")
def get_market_terminal(
    commodity: str = Query("wheat"),
    limit: int = Query(200),
    harvest_days: int = Query(53),
    location: str = Query("Indore"),
):
    """
    Returns a structured terminal response combining:
     - Agmarknet (data.gov.in) mandi data for the commodity
     - Weather (WeatherAPI) for `location`
     - Gemini structured insight influenced by weather + harvest_days
    """

    try:
        # 1) fetch mandi records
        records = fetch_mandi_records(commodity=commodity, limit=limit)

        # 2) normalized market_data
        market_data = normalize_mandi_records(records, commodity)

        # 3) compute summary stats
        modal_prices = [
            m["modal_price"] for m in market_data if m.get("modal_price") is not None
        ]
        avg_price = round(statistics.mean(modal_prices), 2) if modal_prices else 0
        highest_market = (
            max(market_data, key=lambda x: x.get("modal_price", 0))
            if market_data
            else {}
        )
        lowest_market = (
            min(market_data, key=lambda x: x.get("modal_price", float("inf")))
            if market_data
            else {}
        )

        summary_stats = {
            "commodity": commodity.capitalize(),
            "average_price": avg_price,
            "highest_price": highest_market.get("modal_price", 0),
            "highest_market": f"{highest_market.get('market','')}, {highest_market.get('state','')}",
            "lowest_price": lowest_market.get("modal_price", 0),
            "lowest_market": f"{lowest_market.get('market','')}, {lowest_market.get('state','')}",
        }

        # 4) fetch weather data for provided location (affects yield outlook)
        weather = fetch_weather_for_location(location)

        # 5) price forecast for next 7 days
        price_forecast = generate_price_forecast(market_data, days=7)

        # 6) Gemini structured insight (including weather + harvest_days)
        ai_structured = generate_structured_ai_insight(
            commodity=commodity,
            market_data=market_data,
            summary=summary_stats,
            forecast=price_forecast,
            harvest_days=harvest_days,
            weather=weather,
            location=location,
        )

        # 7) Build final response
        response = {
            "timestamp": datetime.datetime.now().strftime("%d %b %Y, %I:%M %p"),
            "commodity": commodity.capitalize(),
            "location": location,
            "summary": summary_stats,
            "market_data": market_data,
            "price_forecast": price_forecast,
            "recommendation": ai_structured.get("recommendation", {}),
            "yield_outlook": ai_structured.get("yield_outlook", {}),
            "price_forecast_comment": ai_structured.get("price_forecast_comment", ""),
            "market_sentiment": ai_structured.get("market_sentiment", {}),
            "optimal_market": ai_structured.get("optimal_market", {}),
            "ai_summary": ai_structured.get(
                "ai_summary", ai_structured.get("reason", "")
            ),
            "ai_reason": ai_structured.get("reason", ""),
        }

        return JSONResponse(content=response)

    except Exception as e:
        print("❌ Terminal Error:", e)
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------
# Fetch mandi records
# -------------------------
def fetch_mandi_records(commodity: str, limit: int = 200):
    try:
        base_url = (
            "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"
        )
        params = {
            "api-key": DATA_GOV_API_KEY,
            "format": "json",
            "limit": limit,
            "filters[commodity]": commodity.capitalize(),
        }
        r = requests.get(base_url, params=params, timeout=12)
        r.raise_for_status()
        out = r.json()
        records = out.get("records", [])
        if not records:
            raise Exception("No mandi data found for commodity")
        return records
    except Exception as e:
        print("⚠️ Mandi Fallback:", e)
        # fallback demo records (schema matched)
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        return [
            {
                "state": "Madhya Pradesh",
                "district": "Indore",
                "market": "Indore",
                "commodity": commodity.capitalize(),
                "variety": "Common",
                "arrival_date": today,
                "min_price": "2200",
                "max_price": "2450",
                "modal_price": "2350",
                "price_unit": "Rs/Quintal",
            },
            {
                "state": "Maharashtra",
                "district": "Nagpur",
                "market": "Nagpur",
                "commodity": commodity.capitalize(),
                "variety": "Common",
                "arrival_date": today,
                "min_price": "2250",
                "max_price": "2480",
                "modal_price": "2380",
                "price_unit": "Rs/Quintal",
            },
            {
                "state": "Rajasthan",
                "district": "Jaipur",
                "market": "Jaipur",
                "commodity": commodity.capitalize(),
                "variety": "Common",
                "arrival_date": today,
                "min_price": "2100",
                "max_price": "2350",
                "modal_price": "2220",
                "price_unit": "Rs/Quintal",
            },
        ]


# -------------------------
# Normalize mandi records
# -------------------------
def normalize_mandi_records(records, commodity_name):
    normalized = []
    for r in records:
        try:
            modal = r.get("modal_price")
            modal_val = None
            if modal is not None:
                try:
                    modal_val = float(modal)
                except Exception:
                    modal_val = None
            normalized.append(
                {
                    "state": r.get("state", ""),
                    "district": r.get("district", ""),
                    "market": r.get("market", ""),
                    "commodity": r.get("commodity", commodity_name.capitalize()),
                    "variety": r.get("variety", ""),
                    "arrival_date": r.get("arrival_date", ""),
                    "min_price": float_or_none(r.get("min_price")),
                    "max_price": float_or_none(r.get("max_price")),
                    "modal_price": modal_val,
                    "unit": r.get("price_unit", "Rs/Quintal"),
                }
            )
        except Exception:
            continue
    return normalized


def float_or_none(x):
    try:
        return float(x)
    except Exception:
        return None


# -------------------------
# Weather fetcher (WeatherAPI)
# -------------------------
def fetch_weather_for_location(location):
    try:
        url = f"http://api.weatherapi.com/v1/forecast.json?key={WEATHER_API_KEY}&q={location}&days=7&aqi=no&alerts=no"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        current = data.get("current", {})
        forecast_days = data.get("forecast", {}).get("forecastday", [])
        simplified_forecast = [
            {
                "date": d.get("date"),
                "avgtemp_c": d["day"].get("avgtemp_c"),
                "totalprecip_mm": d["day"].get("totalprecip_mm"),
                "avghumidity": d["day"].get("avghumidity"),
                "condition": d["day"]["condition"].get("text"),
            }
            for d in forecast_days
        ]
        return {
            "location": data.get("location", {}).get("name", location),
            "country": data.get("location", {}).get("country", "India"),
            "current": {
                "temp_c": current.get("temp_c"),
                "humidity": current.get("humidity"),
                "precip_mm": current.get("precip_mm"),
                "condition": current.get("condition", {}).get("text"),
            },
            "forecast": simplified_forecast,
        }
    except Exception as e:
        print("⚠️ WeatherAPI fallback:", e)
        return {
            "location": location,
            "country": "India",
            "current": {
                "temp_c": None,
                "humidity": None,
                "precip_mm": None,
                "condition": None,
            },
            "forecast": [],
        }


# -------------------------
# Price forecast (7 days)
# -------------------------
def generate_price_forecast(market_data, days=7):
    today = datetime.datetime.utcnow().date()
    prices = [m["modal_price"] for m in market_data if m.get("modal_price") is not None]
    baseline = statistics.median(prices) if prices else 0
    # trend: attempt from earliest to latest arrival_date
    dates = [
        (parse_iso_date_safe(m.get("arrival_date")), m.get("modal_price"))
        for m in market_data
        if parse_iso_date_safe(m.get("arrival_date"))
        and m.get("modal_price") is not None
    ]
    trend_per_day = 0.0
    if len(dates) >= 2:
        dates_sorted = sorted(dates, key=lambda x: x[0])
        first_date, first_price = dates_sorted[0]
        last_date, last_price = dates_sorted[-1]
        span = max((last_date - first_date).days, 1)
        trend_per_day = (last_price - first_price) / span
    else:
        if prices and len(prices) >= 2:
            trend_per_day = (max(prices) - min(prices)) / (7 * 10)
        else:
            trend_per_day = 0.0
    forecast = []
    for i in range(1, days + 1):
        f_date = today + datetime.timedelta(days=i)
        f_price = round(baseline + trend_per_day * i, 2)
        forecast.append(
            {"date": f_date.strftime("%Y-%m-%d"), "forecast_price": f_price}
        )
    return forecast


def parse_iso_date_safe(s):
    if not s or not isinstance(s, str):
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except Exception:
            continue
    try:
        parts = s.split("T")[0]
        return datetime.datetime.strptime(parts, "%Y-%m-%d").date()
    except Exception:
        return None


# -------------------------
# Gemini structured insight
# -------------------------
def generate_structured_ai_insight(
    commodity, market_data, summary, forecast, harvest_days, weather, location
):
    """
    Ask Gemini to return a structured JSON containing:
      - recommendation: {action, confidence, reason}
      - yield_outlook: {change_percent, factors[]}
      - price_forecast_comment: string
      - market_sentiment: {overall, keywords[]}
      - optimal_market: {sell_high:[], buy_low:[]}
      - ai_summary: short summary
      - reason: longer explanation
    """
    try:
        # prepare sample market rows
        small_market = [
            {
                "market": m.get("market"),
                "state": m.get("state"),
                "modal_price": m.get("modal_price"),
            }
            for m in market_data[:30]
        ]

        prompt = f"""
You are AgriPulse Market Intelligence. Return ONLY a valid JSON object (no explanation).

Context:
- Commodity: {commodity.capitalize()}
- Location for weather context: {location}
- Harvest readiness: in {harvest_days} days
- Summary stats: {summary}
- Price forecast (next days): {forecast}
- Weather (current + short forecast): {weather}
- Sample market rows: {small_market}

Tasks:
1) Recommendation: choose one action from BUY / HOLD / SELL for the next 2 weeks. Return confidence (0-100) and a 1-2 sentence reason.
2) Nationwide yield outlook: estimate percent change vs last season (approx), and list 2-4 key factors influencing yield (weather, pests, input cost).
3) Price forecast comment: 1 sentence about near-term price drivers.
4) Market sentiment: overall (positive/neutral/negative) and two keywords.
5) Optimal markets: list top 5 sell_high (market,state,price) and top 5 buy_low (market,state,price).
6) Short ai_summary and a short "reason" field.

Return JSON structure exactly like:
{{
  "recommendation": {{"action":"HOLD","confidence":82,"reason":"..."}},
  "yield_outlook": {{"change_percent":"+1.3%","factors":["...","..."]}},
  "price_forecast_comment":"...",
  "market_sentiment":{{"overall":"positive","keywords":["k1","k2"]}},
  "optimal_market":{{"sell_high":[{{"market":"X","state":"Y","price":123}}],"buy_low":[...] }},
  "ai_summary":"short line",
  "reason":"detailed reasoning (1-3 sentences)"
}}
"""
        ai_resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        text = ai_resp.text.strip()
        try:
            parsed = json.loads(text)
            # validate keys
            if not isinstance(parsed, dict) or "recommendation" not in parsed:
                raise ValueError("Missing keys")
            return parsed
        except Exception as parse_err:
            print("⚠️ Gemini parse failed:", parse_err)
            return fallback_structured_insight(
                commodity, market_data, summary, forecast, harvest_days, weather
            )
    except Exception as e:
        print("⚠️ Gemini call failed:", e)
        return fallback_structured_insight(
            commodity, market_data, summary, forecast, harvest_days, weather
        )


def fallback_structured_insight(
    commodity, market_data, summary, forecast, harvest_days, weather
):
    # compute sells/buys
    sells = sorted(
        [m for m in market_data if m.get("modal_price") is not None],
        key=lambda x: -x["modal_price"],
    )[:5]
    buys = sorted(
        [m for m in market_data if m.get("modal_price") is not None],
        key=lambda x: x["modal_price"],
    )[:5]
    sell_high = [
        {"market": m["market"], "state": m["state"], "price": m["modal_price"]}
        for m in sells
    ]
    buy_low = [
        {"market": m["market"], "state": m["state"], "price": m["modal_price"]}
        for m in buys
    ]

    # naive yield outlook heuristics using weather
    change_percent = "+0.0%"
    factors = []
    # if weather has recent precip, mention moisture
    try:
        if weather.get("current", {}).get("precip_mm"):
            factors.append("recent rainfall")
        if (
            weather.get("current", {}).get("temp_c")
            and weather["current"]["temp_c"] > 34
        ):
            factors.append("high temperatures")
    except Exception:
        pass
    if not factors:
        factors = ["stable weather", "no major risks detected"]

    # naive recommendation heuristic
    baseline = summary.get("average_price", 0)
    next_price = forecast[0]["forecast_price"] if forecast else baseline
    action = "HOLD"
    confidence = 72
    reason = "Market stable — hold and monitor short-term demand."
    if next_price > baseline * 1.02:
        action = "SELL"
        confidence = 80
        reason = "Prices trending up — consider selling to lock gains."
    elif next_price < baseline * 0.98:
        action = "BUY"
        confidence = 75
        reason = "Prices slightly weaker — procurement opportunity."

    sentiment = {"overall": "neutral", "keywords": ["market_stable"]}

    return {
        "recommendation": {
            "action": action,
            "confidence": confidence,
            "reason": reason,
        },
        "yield_outlook": {"change_percent": change_percent, "factors": factors},
        "price_forecast_comment": "Short-term moderate movement expected.",
        "market_sentiment": sentiment,
        "optimal_market": {"sell_high": sell_high, "buy_low": buy_low},
        "ai_summary": reason,
        "reason": reason,
    }
