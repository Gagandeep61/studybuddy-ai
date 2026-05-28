"""
main.py — StudyBuddy AI v4
Changes from v3:
- Groq added as PRIMARY provider (high RPM, free) → OpenRouter as fallback chain
- OCR support: pymupdf (text PDFs) → pytesseract (scanned/image PDFs)
- 502 vs 503: model exhaustion = 502, daily cap = 503 (frontend shows different messages)
- Follow-up call cap removed entirely
- DAILY_LIMIT raised to 100 (Groq handles most traffic, OR rarely bottlenecks)
- Counter increments only on successful LLM response
"""

import os, io, json, re, threading
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
import PyPDF2
import fitz
import pytesseract
from pdf2image import convert_from_bytes

from .prompts import PROCESS_PROMPT, QUIZ_PROMPT, EXTRAS_PROMPT, FOLLOWUP_SYSTEM
from dotenv import load_dotenv
load_dotenv()

# ── LLM clients ───────────────────────────────────────────────────────────────
_groq_client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.environ.get("GROQ_API_KEY"),
)
_or_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ.get("OPENROUTER_API_KEY"),
)

# (client, model) pairs — tried in order on rate limit / error
LLM_MODELS = [
    (_groq_client, "llama-3.3-70b-versatile"),
    (_or_client,   "deepseek/deepseek-v4-flash:free"),
    (_or_client,   "google/gemma-4-26b-a4b-it:free"),
    (_or_client,   "meta-llama/llama-3.3-70b-instruct:free"),
]

# ── File persistence ──────────────────────────────────────────────────────────
DATA_DIR   = Path("/data") if Path("/data").exists() else Path(".")
DAILY_FILE = DATA_DIR / "sb_daily.json"

# ── Constants ─────────────────────────────────────────────────────────────────
DAILY_LIMIT = 100

# ── Lock ──────────────────────────────────────────────────────────────────────
_lock = threading.Lock()

app = FastAPI(title="StudyBuddy AI", version="4.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
# RATE LIMIT GUARD
# ══════════════════════════════════════════════════════════════════════════════

def check_limits(response: Response):
    with _lock:
        if daily_remaining() <= 0:
            raise HTTPException(503, "Daily limit reached. The demo resets at midnight UTC!")
        remaining = daily_remaining()
    response.headers["X-Daily-Remaining"] = str(remaining)
    response.headers["X-Daily-Limit"]     = str(DAILY_LIMIT)


# ══════════════════════════════════════════════════════════════════════════════
# LLM HELPER
# ══════════════════════════════════════════════════════════════════════════════

def call_llm(system: str, user: str) -> str:
    last_error = None
    for llm_client, model in LLM_MODELS:
        try:
            resp = llm_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                max_tokens=4096,
            )
            content = resp.choices[0].message.content
            if content is None:
                last_error = ValueError(f"{model} returned empty content")
                continue
            with _lock:
                _increment_daily()
            return content
        except Exception as e:
            err = str(e).lower()
            if any(x in err for x in ["rate limit", "429", "quota", "provider returned error", "max_tokens", "overloaded"]):
                last_error = e
                continue
            raise
    raise HTTPException(502, "All AI models temporarily busy. Please retry in 60 seconds.")


def parse_json(raw: str) -> dict | list:
    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    return json.loads(cleaned)


# ══════════════════════════════════════════════════════════════════════════════
# REQUEST SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class TextRequest(BaseModel):
    text: str

class FollowUpRequest(BaseModel):
    context:  str
    topic:    str
    question: str


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    with _lock:
        dr = daily_remaining()
    return {
        "status":          "ok",
        "version":         "4.0.0",
        "model":           LLM_MODELS[0][1],
        "fallback_models": [m for _, m in LLM_MODELS[1:]],
        "daily_remaining": dr,
        "daily_limit":     DAILY_LIMIT,
    }


@app.post("/extract-pdf")
async def extract_pdf(file: UploadFile = File(...)):
    """
    Extract text from PDF. No LLM call — does not count toward daily limit.
    Strategy 1: pymupdf    — digital/text-based PDFs (fast)
    Strategy 2: pytesseract — scanned/image PDFs (OCR)
    Strategy 3: PyPDF2     — legacy fallback
    """
    contents = await file.read()

    # Strategy 1: pymupdf
    try:
        doc   = fitz.open(stream=contents, filetype="pdf")
        pages = [page.get_text() for page in doc if page.get_text().strip()]
        doc.close()
        if pages:
            return {"text": "\n\n".join(pages), "method": "pymupdf"}
    except Exception:
        pass

    # Strategy 2: OCR
    try:
        images = convert_from_bytes(contents, dpi=200)
        pages  = [pytesseract.image_to_string(img) for img in images]
        pages  = [p for p in pages if p.strip()]
        if pages:
            return {"text": "\n\n".join(pages), "method": "ocr"}
    except Exception:
        pass

    # Strategy 3: PyPDF2
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(contents))
        pages  = [p.extract_text() for p in reader.pages if p.extract_text()]
        if pages:
            return {"text": "\n\n".join(pages), "method": "pypdf2"}
    except Exception:
        pass

    raise HTTPException(400, "Could not extract text from this PDF. Try pasting text directly.")


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
    """Answer a follow-up question. No cap on follow-ups."""
    check_limits(response)
    user_msg = (
        f"Topic: {req.topic}\n\n"
        f"Simple explanation the student read:\n{req.context[:3000]}\n\n"
        f"Student's question: {req.question}"
    )
    answer = call_llm(FOLLOWUP_SYSTEM, user_msg)
    return {"answer": answer}
