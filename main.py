from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import chat, detect, dashboard, terminal
from google import genai  # ✅ new import
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="AgriPulse Backend")

# ✅ Allow frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Initialize Gemini client (NO configure anymore)
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# ✅ Include routers
app.include_router(chat.router)
app.include_router(detect.router)
app.include_router(dashboard.router)
app.include_router(terminal.router)


@app.get("/")
def home():
    return {"message": "Welcome to AgriPulse API!"}
