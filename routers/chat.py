from fastapi import APIRouter, HTTPException, Request
from google import genai
import os
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

router = APIRouter(prefix="/chat", tags=["AI Chatbot"])


@router.post("/")
async def chat(request: Request):
    try:
        data = await request.json()
        message = data.get("message", "")
        if not message:
            raise HTTPException(status_code=400, detail="Message is required")

        response = client.models.generate_content(
            model="gemini-2.5-flash", contents=message
        )
        return {"response": response.text}

    except Exception as e:
        print("❌ Gemini error:", e)
        raise HTTPException(status_code=500, detail=str(e))
