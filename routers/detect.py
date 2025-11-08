from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from google import genai
import os
from dotenv import load_dotenv
import base64
import io
from PIL import Image

# --- Setup ---
load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

router = APIRouter(prefix="/detect", tags=["Disease Detection"])


@router.post("/")
async def detect_disease(file: UploadFile = File(...)):
    """
    Analyze an uploaded crop leaf image using Google Gemini Vision model.
    Returns detected disease, confidence, and treatment suggestions.
    """

    try:
        # Read file into memory
        contents = await file.read()

        # Convert image bytes into base64 for Gemini Vision API
        encoded_image = base64.b64encode(contents).decode("utf-8")

        # (Optional) Validate it’s a real image
        try:
            Image.open(io.BytesIO(contents))
        except Exception:
            raise HTTPException(
                status_code=400, detail="Uploaded file is not a valid image"
            )

        # Construct AI prompt
        prompt = f"""
        You are an agricultural plant pathology expert AI.
        Analyze the uploaded leaf image and identify any visible disease.
        For your output, return a JSON object with these fields:
        {{
            "detected_disease": "name of disease or 'Healthy'",
            "confidence": "estimated confidence percentage",
            "severity": "low | medium | high",
            "recommended_treatment": "practical treatment steps or note if no issue"
        }}
        Keep the JSON clean and concise, no markdown or explanations.
        """

        # Call Gemini 2.5 Flash Vision model
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": file.content_type,
                                "data": encoded_image,
                            }
                        },
                    ],
                }
            ],
        )

        # Get AI output text
        ai_output = response.text.strip()

        # Try parsing as JSON (if Gemini responds in proper JSON)
        import json

        try:
            parsed = json.loads(ai_output)
        except json.JSONDecodeError:
            # Fallback: return the raw AI text if not valid JSON
            parsed = {"raw_response": ai_output}

        # Attach filename
        parsed["filename"] = file.filename

        return JSONResponse(content=parsed)

    except Exception as e:
        print("❌ Gemini error:", e)
        raise HTTPException(status_code=500, detail=str(e))
