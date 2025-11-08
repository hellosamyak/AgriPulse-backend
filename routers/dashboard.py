from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from google import genai
import requests
import os
import datetime
from dotenv import load_dotenv

# --- Load environment variables ---
load_dotenv()

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

# --- API Keys ---
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
DATA_GOV_API_KEY = os.getenv("DATA_GOV_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- Initialize Gemini Client ---
client = genai.Client(api_key=GEMINI_API_KEY)


@router.get("/")
def get_dashboard(location: str = "Indore"):
    """
    Fetches:
    - Live weather (WeatherAPI)
    - Market prices (data.gov.in)
    - AI summaries and insights (Gemini)
    """

    try:
        # 1️⃣ Fetch Weather
        weather_data = fetch_weather_data(location)

        # 2️⃣ Fetch Mandi Prices (data.gov.in)
        mandi_data = fetch_mandi_data(location)

        # 3️⃣ Fetch Latest Agriculture News (placeholder for now)
        news_data = [
            {
                "headline": "Govt raises MSP for wheat by ₹150/quintal",
                "summary": "Government increases wheat MSP to boost Rabi season earnings.",
                "sentiment": "positive",
            },
            {
                "headline": "Rainfall expected in Northern India this weekend",
                "summary": "IMD predicts moderate rain, farmers advised to delay sowing by 2 days.",
                "sentiment": "neutral",
            },
            {
                "headline": "Soybean exports rise 8% amid global demand",
                "summary": "Soybean prices surge as exports grow globally.",
                "sentiment": "positive",
            },
        ]

        # 4️⃣ AI Summaries and Insights from Gemini
        ai_summary = generate_ai_summary(location, weather_data, mandi_data, news_data)
        ai_crop_insights = generate_multi_crop_insights(
            location, weather_data, mandi_data
        )

        # 5️⃣ Standardized Response
        dashboard_data = {
            "date": datetime.datetime.now().strftime("%d %b %Y"),
            "location": location,
            "weather": weather_data,
            "market_data": mandi_data,
            "news": news_data,
            "ai_summary": ai_summary,
            "ai_crop_insights": ai_crop_insights,
        }

        return JSONResponse(content=dashboard_data)

    except Exception as e:
        print("❌ Dashboard Error:", e)
        raise HTTPException(status_code=500, detail=str(e))


# ============================
# 🌤️ WEATHER DATA
# ============================
def fetch_weather_data(location: str):
    try:
        url = f"http://api.weatherapi.com/v1/forecast.json?key={WEATHER_API_KEY}&q={location}&days=7&aqi=no&alerts=no"
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        data = res.json()

        current = data.get("current", {})
        forecast_days = data.get("forecast", {}).get("forecastday", [])

        return {
            "location": data.get("location", {}).get("name", location),
            "country": data.get("location", {}).get("country", "India"),
            "current": {
                "temp_c": current.get("temp_c"),
                "condition": current.get("condition", {}).get("text"),
                "icon": current.get("condition", {}).get("icon"),
                "humidity": current.get("humidity"),
                "wind_kph": current.get("wind_kph"),
                "precip_mm": current.get("precip_mm"),
            },
            "astro": {
                "sunrise": forecast_days[0].get("astro", {}).get("sunrise", ""),
                "sunset": forecast_days[0].get("astro", {}).get("sunset", ""),
            },
            "forecast": [
                {
                    "date": d["date"],
                    "avgtemp_c": d["day"]["avgtemp_c"],
                    "totalprecip_mm": d["day"]["totalprecip_mm"],
                    "avghumidity": d["day"]["avghumidity"],
                    "condition": d["day"]["condition"]["text"],
                    "icon": d["day"]["condition"]["icon"],
                    "daily_chance_of_rain": d["day"]["daily_chance_of_rain"],
                }
                for d in forecast_days
            ],
        }
    except Exception as e:
        print("⚠️ WeatherAPI fallback:", e)
        return {
            "location": location,
            "country": "India",
            "current": {"temp_c": 30, "condition": "Clear", "humidity": 60},
            "astro": {"sunrise": "06:30 AM", "sunset": "05:45 PM"},
            "forecast": [],
        }


# ============================
# 📊 MARKET DATA (MANDI)
# ============================
def fetch_mandi_data(location: str):
    try:
        url = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"
        params = {
            "api-key": DATA_GOV_API_KEY,
            "format": "json",
            "limit": 10,
            "filters[market]": location,
        }
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        records = res.json().get("records", [])

        if not records:
            raise Exception("No mandi data found")

        return [
            {
                "commodity": r.get("commodity", "Unknown"),
                "market": r.get("market", location),
                "modal_price": float(r.get("modal_price", 0)),
                "max_price": float(r.get("max_price", 0)),
                "min_price": float(r.get("min_price", 0)),
                "arrival_date": r.get("arrival_date", ""),
            }
            for r in records
        ]

    except Exception as e:
        print("⚠️ Mandi Fallback:", e)
        return [
            {"commodity": "Wheat", "market": location, "modal_price": 2300},
            {"commodity": "Soybean", "market": location, "modal_price": 5200},
            {"commodity": "Maize", "market": location, "modal_price": 1850},
        ]


# ============================
# 🧠 GEMINI AI SUMMARIES
# ============================
def generate_ai_summary(location, weather, market, news):
    try:
        prompt = f"""
        You are AgriPulse AI — India's agriculture advisor.

        Using this real data:
        - Weather Forecast: {weather}
        - Market Prices: {market[:5]}
        - News: {news[:3]}

        Summarize for farmers in {location}:
        1️⃣ Weather Outlook
        2️⃣ Market Trends
        3️⃣ Weekly Advisory

        Keep it factual, under 120 words, and friendly.
        """
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        return response.text.strip()
    except Exception as e:
        print("⚠️ Gemini summary fallback:", e)
        return "Stable weather and moderate market trends this week. Monitor rain probability and wheat prices."


# ============================
# 🌾 GEMINI MULTI-CROP INSIGHTS
# ============================
def generate_multi_crop_insights(location, weather, market):
    """
    Asks Gemini to provide 3 recommended crops with confidence levels and reasons.
    """
    try:
        prompt = f"""
        You are *AgriPulse AI* — a next-generation agricultural intelligence system built for precision crop decisioning.

Constant input (do not modify these lines; they are injected dynamically):
        Weather: {weather}
        Mandi Prices: {market[:5]}

Analyze the live data for {location} and output the TOP 3 crops to *plant or sell* this week.

Your analysis must be based on:
- Temperature, rainfall, humidity, and soil conditions of the region  
- Market prices, price momentum, and short-term demand trends  
- Crop seasonality and soil compatibility  
- National and global demand growth of each crop  
- El Niño / La Niña impact on local yield and climate patterns  
- Global economic indicators (IMF, World Bank commodity outlooks)  
- Country-level import/export duties and trade restrictions  
- Feasibility of exporting crops for maximum margins  
- Government policies, MSP updates, or procurement drives  
- Storage, logistics, and supply chain factors that affect price realization  
- Energy/fertilizer costs and other input-side economics  
- Regional risk alerts (pests, diseases, weather extremes)  
- Strategic reserves and inventory cycles that could influence demand  

*Instructions:*
- Output must be strictly valid JSON — no text outside JSON.
- Rank top 3 crops by confidence (0–100).
- For each crop, include detailed reasoning as bullet points showing logic and data links.
- Keep reasoning short, factual, and high signal (3–6 bullets per crop).
- Output only the following JSON structure exactly:

[
  {
    "crop": "Soybean",
    "recommendation_type": "plant" | "sell",
    "confidence": 92,
    "reason": [
      "- Bullet 1: specific reason",
      "- Bullet 2: specific reason",
      "- Bullet 3: specific reason",
      "... up to 6"
    ]
  },
  {
    "crop": "Wheat",
    "recommendation_type": "sell",
    "confidence": 85,
    "reason": [
      "- Bullet 1: specific reason",
      "- Bullet 2: specific reason",
      "- Bullet 3: specific reason"
    ]
  },
  {
    "crop": "Maize",
    "recommendation_type": "plant",
    "confidence": 80,
    "reason": [
      "- Bullet 1: specific reason",
      "- Bullet 2: specific reason",
      "- Bullet 3: specific reason"
    ]
  }
]

*Additional Notes for Model:*
- Always cite weather or market data points numerically when possible (e.g., “Rainfall <10mm next 7 days” or “Price up +6% WoW”).  
- “Confidence” reflects holistic synthesis of agronomic fit, market outlook, and macro trade feasibility — not a statistical probability.  
- If a crop is seasonally unsuited or high-risk, give confidence ≤40 with clear rationale.  
- Prioritize data-driven and economically rational reasoning — avoid generic or repetitive phrasing.  
- Keep response deterministic and concise enough for real-time dashboards.
        """

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )

        import json

        try:
            text = response.text.strip()
            crops = json.loads(text)
            return crops
        except Exception:
            # Fallback to default crops if JSON parsing fails
            return [
                {
                    "crop": "Soybean",
                    "confidence": 90,
                    "reason": "Good demand and suitable humidity",
                },
                {
                    "crop": "Wheat",
                    "confidence": 85,
                    "reason": "Stable prices and rising MSP",
                },
                {
                    "crop": "Maize",
                    "confidence": 78,
                    "reason": "Good returns in dry conditions",
                },
            ]

    except Exception as e:
        print("⚠️ Gemini Crop Fallback:", e)
        return [
            {"crop": "Wheat", "confidence": 80, "reason": "Favorable conditions"},
            {"crop": "Maize", "confidence": 75, "reason": "Moderate temperatures"},
            {"crop": "Soybean", "confidence": 70, "reason": "Stable market rates"},
        ]
