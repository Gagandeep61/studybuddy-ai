"""
main.py — StudyBuddy AI v3
Rate limiting: single global daily cap of 200 calls, resets at midnight UTC.
Persisted to /data/sb_daily.json on HuggingFace (survives container restarts).
Threading lock prevents concurrent writes corrupting the JSON file.
"""

import os, io, json, re, threading
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
import PyPDF2

from .prompts import PROCESS_PROMPT, QUIZ_PROMPT, EXTRAS_PROMPT, FOLLOWUP_SYSTEM
from dotenv import load_dotenv
load_dotenv()

# ── LLM client ────────────────────────────────────────────────────────────────
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ.get("OPENROUTER_API_KEY"),
)
MODEL = "deepseek/deepseek-v3:free"

# ── File persistence ──────────────────────────────────────────────────────────
# /data exists on HuggingFace Spaces and survives restarts.
# Falls back to current directory for local development.
DATA_DIR   = Path("/data") if Path("/data").exists() else Path(".")
DAILY_FILE = DATA_DIR / "sb_daily.json"

# ── Constants ─────────────────────────────────────────────────────────────────
DAILY_LIMIT    = 200
FOLLOWUP_LIMIT = 3

# ── Lock — one thread at a time reads/writes the daily JSON ──────────────────
_lock = threading.Lock()

app = FastAPI(title="StudyBuddy AI", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # replace * with your Vercel URL after deploying
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════════════════
# DAILY COUNTER
# ══════════════════════════════════════════════════════════════════════════════

def _load(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default

def _save(path: Path, data):
    path.write_text(json.dumps(data))

def _get_daily() -> dict:
    store = _load(DAILY_FILE, {"date": None, "count": 0})
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if store["date"] != today:
        store = {"date": today, "count": 0}
        _save(DAILY_FILE, store)
    return store

def _increment_daily():
    store = _get_daily()
    store["count"] += 1
    _save(DAILY_FILE, store)

def daily_remaining() -> int:
    return max(0, DAILY_LIMIT - _get_daily()["count"])


# ══════════════════════════════════════════════════════════════════════════════
# RATE LIMIT CHECK — called at the top of every endpoint
# ══════════════════════════════════════════════════════════════════════════════

def check_limits(response: Response):
    with _lock:
        if daily_remaining() <= 0:
            raise HTTPException(503, "Daily limit reached. The demo resets at midnight UTC!")
        _increment_daily()
        remaining = daily_remaining()
    response.headers["X-Daily-Remaining"] = str(remaining)
    response.headers["X-Daily-Limit"]     = str(DAILY_LIMIT)


# ══════════════════════════════════════════════════════════════════════════════
# LLM HELPER
# ══════════════════════════════════════════════════════════════════════════════

def call_llm(system: str, user: str) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    )
    return response.choices[0].message.content

def parse_json(raw: str) -> dict | list:
    # Strip any markdown fences the model may add despite instructions
    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    return json.loads(cleaned)


# ══════════════════════════════════════════════════════════════════════════════
# REQUEST SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class TextRequest(BaseModel):
    text: str

class FollowUpRequest(BaseModel):
    context:        str
    topic:          str
    question:       str
    followup_count: int   # frontend tracks how many follow-ups have been sent


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    with _lock:
        dr = daily_remaining()
    return {"status": "ok", "model": MODEL, "daily_remaining": dr}


@app.post("/extract-pdf")
async def extract_pdf(response: Response, file: UploadFile = File(...)):
    """Extract text from an uploaded PDF. Counts as 1 daily call."""
    check_limits(response)
    contents = await file.read()
    reader   = PyPDF2.PdfReader(io.BytesIO(contents))
    pages    = [p.extract_text() for p in reader.pages if p.extract_text()]
    text     = "\n\n".join(pages)
    if not text.strip():
        raise HTTPException(400, "Could not extract text. Use a text-based PDF or paste text directly.")
    return {"text": text}


@app.post("/process")
def process_material(req: TextRequest, response: Response):
    """Analyse study material — returns topic, difficulty, summary, key terms."""
    check_limits(response)
    if not req.text.strip():
        raise HTTPException(400, "Text cannot be empty.")

    raw = call_llm(PROCESS_PROMPT, f"Study material:\n\n{req.text[:12000]}")
    try:
        data = parse_json(raw)
    except Exception:
        raise HTTPException(500, f"Parse error: {raw[:200]}")

    words                  = len(req.text.split())
    data["word_count"]     = words
    data["study_time_min"] = max(1, round(words / 200))
    return data


@app.post("/generate-quiz")
def generate_quiz(req: TextRequest, response: Response):
    """Generate 10 MCQs with explanations and memory tips."""
    check_limits(response)
    if not req.text.strip():
        raise HTTPException(400, "Text cannot be empty.")

    raw = call_llm(QUIZ_PROMPT, f"Study material:\n\n{req.text[:12000]}")
    try:
        data = parse_json(raw)
    except Exception:
        raise HTTPException(500, f"Parse error: {raw[:200]}")

    return {"questions": data}


@app.post("/generate-extras")
def generate_extras(req: TextRequest, response: Response):
    """One call returns flashcards + exam prep + simple explanation."""
    check_limits(response)
    if not req.text.strip():
        raise HTTPException(400, "Text cannot be empty.")

    raw = call_llm(EXTRAS_PROMPT, f"Study material:\n\n{req.text[:12000]}")
    try:
        data = parse_json(raw)
    except Exception:
        raise HTTPException(500, f"Parse error: {raw[:200]}")

    return data


@app.post("/followup")
def followup(req: FollowUpRequest, response: Response):
    """Answer a follow-up question in plain language."""
    if req.followup_count >= FOLLOWUP_LIMIT:
        raise HTTPException(400, f"Follow-up limit reached ({FOLLOWUP_LIMIT} per session).")

    check_limits(response)
    user_msg = (
        f"Topic: {req.topic}\n\n"
        f"Simple explanation the student read:\n{req.context[:3000]}\n\n"
        f"Student's question: {req.question}"
    )
    answer = call_llm(FOLLOWUP_SYSTEM, user_msg)
    return {"answer": answer}
    