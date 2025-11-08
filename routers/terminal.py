from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
import requests
import os
import datetime
import json
import statistics
import random
import pandas as pd
from pathlib import Path
from google import genai
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/terminal", tags=["Agri Terminal"])

# =============================
# 🔑 API KEYS & CONFIG
# =============================
DATA_GOV_API_KEY = os.getenv("DATA_GOV_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DISTANCEMATRIX_API_KEY = os.getenv("DISTANCEMATRIX_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

DATA_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "international_prices_synthetic_expanded_inr.csv"
)


# ============================================================
# 🌾 MAIN TERMINAL ENDPOINT
# ============================================================
@router.get("/")
def get_market_terminal(
    commodity: str = Query("wheat"),
    limit: int = Query(200),
    harvest_days: int = Query(53),
    location: str = Query("Indore"),
):
    try:
        # 1️⃣ Fetch Mandi data
        records = fetch_mandi_records(commodity=commodity, limit=limit)
        market_data = normalize_mandi_records(records, commodity)

        # 2️⃣ Compute summary
        modal_prices = [m["modal_price"] for m in market_data if m.get("modal_price")]
        avg_price = round(statistics.mean(modal_prices), 2) if modal_prices else 0

        highest_market = max(market_data, key=lambda x: x.get("modal_price", 0))
        lowest_market = min(
            market_data, key=lambda x: x.get("modal_price", float("inf"))
        )

        summary = {
            "commodity": commodity.capitalize(),
            "average_price": avg_price,
            "highest_price": highest_market.get("modal_price", 0),
            "highest_market": f"{highest_market.get('market','')}, {highest_market.get('state','')}",
            "lowest_price": lowest_market.get("modal_price", 0),
            "lowest_market": f"{lowest_market.get('market','')}, {lowest_market.get('state','')}",
        }

        # 3️⃣ Fetch Weather
        weather = fetch_weather_for_location(location)

        # 4️⃣ Forecast Prices
        price_forecast = generate_price_forecast(market_data, days=7)

        # 5️⃣ AI Insight
        ai_structured = generate_structured_ai_insight(
            commodity,
            market_data,
            summary,
            price_forecast,
            harvest_days,
            weather,
            location,
        )

        # 6️⃣ Final Response
        return JSONResponse(
            content={
                "timestamp": datetime.datetime.now().strftime("%d %b %Y, %I:%M %p"),
                "commodity": commodity.capitalize(),
                "location": location,
                "summary": summary,
                "market_data": market_data,
                "price_forecast": price_forecast,
                "recommendation": ai_structured.get("recommendation", {}),
                "yield_outlook": ai_structured.get("yield_outlook", {}),
                "price_forecast_comment": ai_structured.get(
                    "price_forecast_comment", ""
                ),
                "market_sentiment": ai_structured.get("market_sentiment", {}),
                "optimal_market": ai_structured.get("optimal_market", {}),
                "ai_summary": ai_structured.get("ai_summary", ""),
                "ai_reason": ai_structured.get("reason", ""),
            }
        )

    except Exception as e:
        print("❌ Terminal Error:", e)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 🏪 FETCH & NORMALIZE MANDI DATA
# ============================================================
def fetch_mandi_records(commodity: str, limit: int = 200):
    try:
        url = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"
        params = {
            "api-key": DATA_GOV_API_KEY,
            "format": "json",
            "limit": limit,
            "filters[commodity]": commodity.capitalize(),
        }
        r = requests.get(url, params=params, timeout=12)
        data = r.json().get("records", [])
        if not data:
            raise Exception("No mandi data found.")
        return data
    except Exception as e:
        print("⚠️ Using fallback mandi data:", e)
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
        ]


def normalize_mandi_records(records, commodity_name):
    normalized = []
    for r in records:
        try:
            modal_val = float(r["modal_price"])
            normalized.append(
                {
                    "state": r.get("state", ""),
                    "district": r.get("district", ""),
                    "market": r.get("market", ""),
                    "commodity": commodity_name.capitalize(),
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


# ============================================================
# 🌦 WEATHER FETCHER
# ============================================================
def fetch_weather_for_location(location):
    try:
        url = f"http://api.weatherapi.com/v1/forecast.json?key={WEATHER_API_KEY}&q={location}&days=7"
        data = requests.get(url, timeout=10).json()
        return {
            "location": data.get("location", {}).get("name", location),
            "country": data.get("location", {}).get("country", "India"),
            "current": data.get("current", {}),
        }
    except Exception as e:
        print("⚠️ Weather Fallback:", e)
        return {"location": location, "country": "India", "current": {}}


# ============================================================
# 📈 PRICE FORECAST
# ============================================================
def generate_price_forecast(market_data, days=7):
    today = datetime.datetime.utcnow().date()
    prices = [m["modal_price"] for m in market_data if m.get("modal_price")]
    baseline = statistics.median(prices) if prices else 0
    forecast = []
    for i in range(1, days + 1):
        forecast.append(
            {
                "date": (today + datetime.timedelta(days=i)).strftime("%Y-%m-%d"),
                "forecast_price": round(baseline + random.uniform(-50, 50), 2),
            }
        )
    return forecast


# ============================================================
# 🤖 GEMINI STRUCTURED AI INSIGHT
# ============================================================
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
        small_market = [
            {
                "market": m.get("market"),
                "state": m.get("state"),
                "modal_price": m.get("modal_price"),
            }
            for m in market_data[:25]
        ]

        prompt = f"""
You are AgriPulse Market Intelligence. Return ONLY a valid JSON object (no explanations).

Context:
- Commodity: {commodity.capitalize()}
- Location: {location}
- Harvest readiness: in {harvest_days} days
- Summary stats: {summary}
- Price forecast (next days): {forecast}
- Weather summary: {weather}
- Sample markets: {small_market}

Tasks:
1️⃣ Recommendation: choose one action from BUY / HOLD / SELL for next 2 weeks. Return confidence (0–100) and reason.
2️⃣ Yield Outlook: percent change vs last season (approx) and 2–4 influencing factors.
3️⃣ Price Forecast Comment: 1 sentence on near-term drivers.
4️⃣ Market Sentiment: overall (positive/neutral/negative) and 2 keywords.
5️⃣ Optimal Markets: top 5 sell_high (market,state,price) and top 5 buy_low.
6️⃣ ai_summary (short) and reason (1–3 sentence reasoning).

Return JSON like:
{{
  "recommendation": {{"action":"SELL","confidence":81,"reason":"..."}},
  "yield_outlook": {{"change_percent":"+2.4%","factors":["...","..."]}},
  "price_forecast_comment":"...",
  "market_sentiment":{{"overall":"positive","keywords":["export","demand"]}},
  "optimal_market":{{"sell_high":[{{"market":"X","state":"Y","price":123}}],"buy_low":[...]}},
  "ai_summary":"short line",
  "reason":"detailed reasoning (2 sentences)"
}}
"""

        ai_resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        text = ai_resp.text.strip()

        # Try parsing Gemini's JSON
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "recommendation" in parsed:
                return parsed
            raise ValueError("Invalid JSON structure from Gemini")
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


# ------------------------------------------------------------
# 🧩 Fallback Insight (used if Gemini fails or API unavailable)
# ------------------------------------------------------------
def fallback_structured_insight(
    commodity, market_data, summary, forecast, harvest_days, weather
):
    # Compute top sell and buy markets
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

    # Simple yield heuristic
    factors = []
    if weather.get("current", {}).get("precip_mm", 0) > 0:
        factors.append("recent rainfall")
    if weather.get("current", {}).get("temp_c", 0) > 34:
        factors.append("high temperatures")
    if not factors:
        factors = ["stable weather", "no major issues"]

    # Basic trend heuristic
    baseline = summary.get("average_price", 0)
    next_price = forecast[0]["forecast_price"] if forecast else baseline
    if next_price > baseline * 1.02:
        action, conf, reason = (
            "SELL",
            80,
            "Prices are trending upward — ideal for selling.",
        )
    elif next_price < baseline * 0.98:
        action, conf, reason = "BUY", 75, "Prices slightly down — opportunity to buy."
    else:
        action, conf, reason = "HOLD", 70, "Market stable — hold for short term."

    return {
        "recommendation": {"action": action, "confidence": conf, "reason": reason},
        "yield_outlook": {"change_percent": "+0.3%", "factors": factors},
        "price_forecast_comment": "Minor short-term variations expected.",
        "market_sentiment": {"overall": "neutral", "keywords": ["steady", "moderate"]},
        "optimal_market": {"sell_high": sell_high, "buy_low": buy_low},
        "ai_summary": reason,
        "reason": reason,
    }


# ============================================================
# 🌍 TRADE SIMULATION ENGINE
# ============================================================


def load_international_prices():
    if not DATA_PATH.exists():
        raise FileNotFoundError("International dataset missing.")
    return pd.read_csv(DATA_PATH)


def get_distance_km(source, destination):
    try:
        url = (
            f"https://api.distancematrix.ai/maps/api/distancematrix/json?"
            f"origins={source}&destinations={destination}&key={DISTANCEMATRIX_API_KEY}"
        )
        res = requests.get(url, timeout=12)
        element = res.json()["rows"][0]["elements"][0]
        if element.get("status") != "OK":
            return estimate_distance_fallback(source, destination)
        dist = element["distance"]["text"]
        return float(dist.replace(" km", "").replace(",", ""))
    except Exception:
        return estimate_distance_fallback(source, destination)


def estimate_distance_fallback(source, destination):
    src, dst = source.lower(), destination.lower()
    routes = {
        ("mumbai", "novorossiysk"): 4800,
        ("mumbai", "dubai"): 1900,
        ("mumbai", "singapore"): 3900,
        ("kolkata", "dhaka"): 250,
        ("chennai", "jakarta"): 3600,
        ("mumbai", "new york"): 12500,
        ("mumbai", "rotterdam"): 7100,
        ("pune", "delhi"): 1450,
        ("indore", "mumbai"): 585,
        ("nagpur", "kolkata"): 970,
    }
    for (a, b), d in routes.items():
        if a in src and b in dst:
            return d
    return 5000


def compute_trade_profit(buy_price, sell_price, distance_km, qty_tonnes, domestic=True):
    rate = random.randint(50, 100) if domestic else random.randint(120, 200)
    logistics_cost = rate * distance_km
    gross_profit = (sell_price - buy_price) * qty_tonnes
    net_profit = gross_profit - logistics_cost
    roi = (net_profit / (buy_price * qty_tonnes)) * 100 if buy_price > 0 else 0
    return logistics_cost, net_profit, roi


@router.get("/simulate-trade")
def simulate_trade(
    commodity: str = Query(...),
    source: str = Query(...),
    destination: str = Query(...),
    qty_tonnes: float = Query(20.0),
    domestic: bool = Query(False),
):
    try:
        if domestic:
            # Domestic using Mandi API
            df = pd.DataFrame(
                normalize_mandi_records(fetch_mandi_records(commodity), commodity)
            )
            src = df[df["market"].str.contains(source, case=False, na=False)]
            dst = df[df["market"].str.contains(destination, case=False, na=False)]
            if src.empty or dst.empty:
                raise HTTPException(
                    status_code=404, detail="Source/destination not found in mandi data"
                )
            buy_price = float(src.iloc[0]["modal_price"]) * 10
            sell_price = float(dst.iloc[0]["modal_price"]) * 10
        else:
            # International using CSV
            df = load_international_prices()
            df_commodity = df[df["Commodity"].str.lower() == commodity.lower()]
            src = df_commodity[
                df_commodity["Region"].str.contains(source, case=False, na=False)
            ]
            dst = df_commodity[
                df_commodity["Region"].str.contains(destination, case=False, na=False)
            ]
            if src.empty or dst.empty:
                raise HTTPException(
                    status_code=404, detail="Source/destination not found in dataset"
                )
            buy_price = float(src.iloc[0]["Price_INR_per_Tonne"])
            sell_price = float(dst.iloc[0]["Price_INR_per_Tonne"])

        distance_km = get_distance_km(source, destination)
        logistics_cost, net_profit, roi = compute_trade_profit(
            buy_price, sell_price, distance_km, qty_tonnes, domestic
        )

        return JSONResponse(
            content={
                "mode": "Domestic" if domestic else "International",
                "domestic": domestic,
                "commodity": commodity.capitalize(),
                "source": source,
                "destination": destination,
                "distance_km": round(distance_km, 2),
                "buy_price_inr_per_tonne": round(buy_price, 2),
                "sell_price_inr_per_tonne": round(sell_price, 2),
                "qty_tonnes": qty_tonnes,
                "logistics_cost_inr": round(logistics_cost, 2),
                "net_profit_inr": round(net_profit, 2),
                "roi_percent": round(roi, 2),
                "profitable": net_profit > 0,
            }
        )

    except Exception as e:
        print("❌ Trade simulation error:", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/international-options")
def get_international_options():
    """
    Returns a list of available commodities and ports from the international CSV dataset.
    """
    try:
        df = load_international_prices()
        commodities = sorted(df["Commodity"].unique().tolist())
        ports = sorted(df["Region"].unique().tolist())
        return JSONResponse(content={"commodities": commodities, "ports": ports})
    except Exception as e:
        print("⚠️ Failed to load options:", e)
        raise HTTPException(status_code=500, detail=str(e))
