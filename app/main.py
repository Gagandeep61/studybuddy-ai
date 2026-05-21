"""
main.py — StudyBuddy AI v2
Rate limiting design:
  - Each browser gets a UUID session ID (stored in localStorage, sent in header)
  - Per-session: 20 calls allowed per 3-hour window
  - If the same IP has created 2+ sessions (localStorage clearing trick), budget halves to 10
  - Global daily cap: 200 calls — resets at midnight UTC
  - Both counters persist to /data/*.json on HuggingFace (survives container restarts)
  - Threading lock prevents concurrent requests corrupting the JSON files
"""

import os, io, json, re, threading
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import google.generativeai as genai
import PyPDF2

from .prompts import PROCESS_PROMPT, QUIZ_PROMPT, EXTRAS_PROMPT, FOLLOWUP_SYSTEM

# ── Gemini client ─────────────────────────────────────────────────────────────
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
MODEL = "gemini-2.5-flash"

# ── File persistence ──────────────────────────────────────────────────────────
# /data exists on HuggingFace Spaces and survives restarts.
# Locally it falls back to the current directory for development.
DATA_DIR     = Path("/data") if Path("/data").exists() else Path(".")
SESSION_FILE = DATA_DIR / "sb_sessions.json"
DAILY_FILE   = DATA_DIR / "sb_daily.json"

# ── Constants ─────────────────────────────────────────────────────────────────
SESSION_LIMIT        = 20
SESSION_WINDOW_HOURS = 3
DAILY_LIMIT          = 200
FOLLOWUP_LIMIT       = 3

# ── Lock — one thread at a time reads/writes the JSON files ──────────────────
_lock = threading.Lock()

app = FastAPI(title="StudyBuddy AI", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # replace * with your Vercel URL after deploying
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════════════════
# PERSISTENCE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _load(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default

def _save(path: Path, data):
    path.write_text(json.dumps(data))


# ── Daily counter ─────────────────────────────────────────────────────────────

def _get_daily() -> dict:
    store = _load(DAILY_FILE, {"date": None, "count": 0})
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if store["date"] != today:
        store = {"date": today, "count": 0}  # new day, reset
        _save(DAILY_FILE, store)
    return store

def _increment_daily():
    store = _get_daily()
    store["count"] += 1
    _save(DAILY_FILE, store)

def daily_remaining() -> int:
    return max(0, DAILY_LIMIT - _get_daily()["count"])


# ── Session counter ───────────────────────────────────────────────────────────

def _get_session(session_id: str, ip: str) -> dict:
    """Return session entry, resetting if the 3-hour window has expired."""
    store = _load(SESSION_FILE, {})
    now   = datetime.utcnow()
    entry = store.get(session_id)

    if entry:
        window_start = datetime.fromisoformat(entry["window_start"])
        if now - window_start > timedelta(hours=SESSION_WINDOW_HOURS):
            # Window expired — reset count, increment reset_count for abuse tracking
            entry["count"]       = 0
            entry["window_start"] = now.isoformat()
            entry["reset_count"] = entry.get("reset_count", 0) + 1
            store[session_id]    = entry
            _save(SESSION_FILE, store)
    else:
        # New session — check if this IP has been clearing localStorage repeatedly
        ip_sessions  = [s for s in store.values() if s.get("ip") == ip]
        prior_resets = sum(s.get("reset_count", 0) for s in ip_sessions)
        entry = {
            "count":          0,
            "window_start":   now.isoformat(),
            "ip":             ip,
            "reset_count":    0,
            "reduced_budget": prior_resets >= 2,  # halve budget if suspicious
        }
        store[session_id] = entry
        _save(SESSION_FILE, store)

    return entry

def _increment_session(session_id: str, ip: str) -> dict:
    store          = _load(SESSION_FILE, {})
    _get_session(session_id, ip)   # ensure entry exists and is not expired
    store          = _load(SESSION_FILE, {})  # reload (get_session may have written)
    store[session_id]["count"] += 1
    _save(SESSION_FILE, store)
    return store[session_id]

def _effective_limit(entry: dict) -> int:
    return SESSION_LIMIT // 2 if entry.get("reduced_budget") else SESSION_LIMIT


# ══════════════════════════════════════════════════════════════════════════════
# RATE LIMIT CHECK — called at the top of every endpoint
# ══════════════════════════════════════════════════════════════════════════════

def check_limits(request: Request) -> tuple[dict, int]:
    session_id = request.headers.get("X-Session-ID", "")
    ip         = request.client.host if request.client else "unknown"

    if not session_id:
        raise HTTPException(400, "Missing X-Session-ID header.")

    with _lock:
        # Check 1: global daily cap
        if daily_remaining() <= 0:
            raise HTTPException(503, "Daily limit reached. The demo resets at midnight UTC!")

        # Check 2: per-session limit
        entry = _get_session(session_id, ip)
        limit = _effective_limit(entry)
        if entry["count"] >= limit:
            window_start = datetime.fromisoformat(entry["window_start"])
            reset_at     = window_start + timedelta(hours=SESSION_WINDOW_HOURS)
            mins_left    = max(1, int((reset_at - datetime.utcnow()).total_seconds() / 60))
            raise HTTPException(429, f"Session limit reached ({limit} calls). Resets in {mins_left} minutes.")

        # Both checks passed — increment both counters
        entry = _increment_session(session_id, ip)
        _increment_daily()

    return entry, limit


def _set_limit_headers(response: Response, entry: dict, limit: int):
    """Attach limit state to every response so the frontend can update the UI."""
    used         = entry["count"]
    remaining    = max(0, limit - used)
    window_start = datetime.fromisoformat(entry["window_start"])
    reset_at     = window_start + timedelta(hours=SESSION_WINDOW_HOURS)
    mins_left    = max(0, int((reset_at - datetime.utcnow()).total_seconds() / 60))

    response.headers["X-Calls-Used"]      = str(used)
    response.headers["X-Calls-Remaining"] = str(remaining)
    response.headers["X-Calls-Limit"]     = str(limit)
    response.headers["X-Reset-Minutes"]   = str(mins_left)
    response.headers["X-Daily-Remaining"] = str(daily_remaining())


# ══════════════════════════════════════════════════════════════════════════════
# GEMINI HELPER
# ══════════════════════════════════════════════════════════════════════════════

def call_gemini(system: str, user: str) -> str:
    model    = genai.GenerativeModel(model_name=MODEL, system_instruction=system)
    response = model.generate_content(user)
    return response.text

def parse_json(raw: str) -> dict | list:
    # Strip any markdown fences Gemini might have added despite being told not to
    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    return json.loads(cleaned)


# ══════════════════════════════════════════════════════════════════════════════
# REQUEST SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class TextRequest(BaseModel):
    text: str

class FollowUpRequest(BaseModel):
    context:       str
    topic:         str
    question:      str
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
async def extract_pdf(request: Request, response: Response, file: UploadFile = File(...)):
    """Extract text from uploaded PDF. Counts as 1 API call."""
    entry, limit = check_limits(request)
    contents = await file.read()
    reader   = PyPDF2.PdfReader(io.BytesIO(contents))
    pages    = [p.extract_text() for p in reader.pages if p.extract_text()]
    text     = "\n\n".join(pages)
    if not text.strip():
        raise HTTPException(400, "Could not extract text. Use a text-based PDF or paste text directly.")
    _set_limit_headers(response, entry, limit)
    return {"text": text}


@app.post("/process")
def process_material(req: TextRequest, request: Request, response: Response):
    """Analyse study material — returns topic, difficulty, summary, key terms."""
    entry, limit = check_limits(request)
    if not req.text.strip():
        raise HTTPException(400, "Text cannot be empty.")

    raw = call_gemini(PROCESS_PROMPT, f"Study material:\n\n{req.text[:12000]}")
    try:
        data = parse_json(raw)
    except Exception:
        raise HTTPException(500, f"Parse error: {raw[:200]}")

    words              = len(req.text.split())
    data["word_count"]     = words
    data["study_time_min"] = max(1, round(words / 200))

    _set_limit_headers(response, entry, limit)
    return data


@app.post("/generate-quiz")
def generate_quiz(req: TextRequest, request: Request, response: Response):
    """Generate 10 MCQs with pre-embedded per-option explanations and memory tips.
    No /evaluate-answer endpoint needed — all feedback data is in this response."""
    entry, limit = check_limits(request)
    if not req.text.strip():
        raise HTTPException(400, "Text cannot be empty.")

    raw = call_gemini(QUIZ_PROMPT, f"Study material:\n\n{req.text[:12000]}")
    try:
        data = parse_json(raw)
    except Exception:
        raise HTTPException(500, f"Parse error: {raw[:200]}")

    _set_limit_headers(response, entry, limit)
    return {"questions": data}


@app.post("/generate-extras")
def generate_extras(req: TextRequest, request: Request, response: Response):
    """One call returns flashcards + exam prep + simple explanation."""
    entry, limit = check_limits(request)
    if not req.text.strip():
        raise HTTPException(400, "Text cannot be empty.")

    raw = call_gemini(EXTRAS_PROMPT, f"Study material:\n\n{req.text[:12000]}")
    try:
        data = parse_json(raw)
    except Exception:
        raise HTTPException(500, f"Parse error: {raw[:200]}")

    _set_limit_headers(response, entry, limit)
    return data


@app.post("/followup")
def followup(req: FollowUpRequest, request: Request, response: Response):
    """Answer a follow-up question. Frontend enforces the 3-question cap,
    backend validates it too so it cannot be bypassed via direct API calls."""
    if req.followup_count >= FOLLOWUP_LIMIT:
        raise HTTPException(400, f"Follow-up limit reached ({FOLLOWUP_LIMIT} per session).")

    entry, limit = check_limits(request)
    user_msg     = (
        f"Topic: {req.topic}\n\n"
        f"Simple explanation the student read:\n{req.context[:3000]}\n\n"
        f"Student's question: {req.question}"
    )
    answer = call_gemini(FOLLOWUP_SYSTEM, user_msg)
    _set_limit_headers(response, entry, limit)
    return {"answer": answer}
