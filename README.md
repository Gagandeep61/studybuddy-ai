<div align="center">

# 📚 StudyBuddy AI

**Upload your notes or a PDF — get a quiz, flashcards, exam prep, and a plain-language explanation. Instantly.**

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Vercel-000000?style=for-the-badge&logo=vercel)](https://studybuddy-one-olive.vercel.app)
[![Backend](https://img.shields.io/badge/Backend-HuggingFace%20Spaces-FFD21E?style=for-the-badge&logo=huggingface&logoColor=black)](https://gagan61-studybuddy-ai.hf.space)
[![CI/CD](https://img.shields.io/github/actions/workflow/status/Gagandeep61/studybuddy-ai/deploy.yml?style=for-the-badge&label=CI%2FCD&logo=githubactions&logoColor=white)](https://github.com/Gagandeep61/studybuddy-ai/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

</div>

---

## 30-Second Pitch

Students spend hours passively re-reading notes before exams. Active recall — self-testing — is consistently shown to be **2–3× more effective** for long-term retention than re-reading.<sup>[1]</sup> But creating quizzes, flashcards, and exam-style questions from raw notes takes more hours of prep work on top of an already exhausting study schedule.

StudyBuddy AI eliminates that prep entirely. Upload any study material — a PDF chapter, pasted lecture notes, a copied textbook section — and in under 30 seconds you have a **10-question MCQ quiz** with per-option explanations, **8 flip flashcards** with known/review tracking, **5 likely exam questions** with hints, and a **plain-English breakdown** of the entire topic written like you're 10. One upload, five study tools.

<sup>[1] Roediger & Karpicke (2006), Psychological Science — "Test-Enhanced Learning"</sup>

---

## ⚡ Quick Stats

| Metric | Value |
|---|---|
| **Input formats** | PDF (text-based · scanned/image) · pasted text |
| **MCQ questions generated** | 10 — mixed difficulty (3 easy · 4 medium · 3 hard) |
| **Flashcards generated** | 8 term–definition pairs per session |
| **Exam prep questions** | 5 likely exam questions with hints and key points |
| **Primary LLM** | Groq — Llama 3.3 70B Versatile (fastest free inference) |
| **Fallback chain** | 3 OpenRouter models — automatic, invisible to user |
| **LLM calls per full session** | ~3 (process · quiz · extras) |
| **Daily cap** | 100 calls — shared global, persisted across restarts |
| **PDF extraction strategies** | 3 — PyMuPDF → Tesseract OCR → PyPDF2 |
| **Frontend dependencies** | 0 — vanilla HTML, CSS, JS |

---

## 🔴 The Problem

| Problem | Reality |
|---|---|
| Active recall is proven superior to passive re-reading | Most students still re-read notes the night before |
| Creating good MCQs takes 10–20 minutes per question | Students skip self-testing because the setup cost is too high |
| Flashcard apps require manual input | Anki, Quizlet — hours of card creation before you can study |
| Dense academic text is hard to digest quickly | Jargon, passive voice, and assumed context block comprehension |

StudyBuddy removes the barrier between having notes and actively studying from them.

---

## ✅ Features

| Feature | Detail |
|---|---|
| **Smart Analysis** | Topic, subject area, difficulty level (with reasoning), 5 key concepts, 5 key terms |
| **10-Question Quiz** | MCQs with per-option explanations, memory tips, topic tags, and difficulty mix |
| **8 Flashcards** | Flip animation, known/review tracking, shuffle, session progress counter |
| **Exam Prep** | 5 likely exam questions with one-sentence hints and 3 key answer points each |
| **Explain Simply** | Full topic in plain language with real-world analogies, written for a 10-year-old |
| **Follow-up Q&A** | Ask anything about the topic — answered in 2–4 plain sentences |
| **Lazy tab loading** | Data fetched on first tab visit — one `/generate-extras` call feeds 3 tabs |
| **3-strategy PDF extraction** | Text PDFs → scanned PDFs → legacy fallback, fully automatic |
| **Multi-provider fallback** | Groq primary → 3 OpenRouter models — zero user-visible failures on rate limit |
| **Loading overlay system** | Context-aware messages per operation (reading PDF, building quiz, etc.) |
| **Warm light UI** | Cream background, amber accent — readable during long study sessions |

---

## 🏗️ Architecture

```
Study material (PDF or text)
    ↓  /extract-pdf  →  PyMuPDF → Tesseract OCR → PyPDF2 (cascade, no LLM)
    ↓  /process      →  LLM → topic · difficulty · concepts · key terms
    ↓  /generate-quiz    →  LLM → 10 MCQs · explanations · memory tips
    ↓  /generate-extras  →  LLM → flashcards · exam questions · simple explanation
    ↓  Frontend      →  lazy tab loading · flip cards · quiz engine · follow-up chat
```

```
┌──────────────────────────────────────────────────────────┐
│                   Frontend (Vercel)                       │
│          HTML · CSS (Warm Light) · Vanilla JS             │
│                                                           │
│  Tab nav · Quiz engine · Flashcard flip · Loading overlay │
└─────────────────────┬─────────────────────────────────────┘
                      │  HTTPS REST
┌─────────────────────▼─────────────────────────────────────┐
│              Backend (HF Spaces · Docker)                  │
│                FastAPI + Python 3.11                       │
│                                                           │
│  ┌───────────────────┐   ┌──────────────────────────────┐  │
│  │  PDF Extraction   │   │     LLM Fallback Chain       │  │
│  │                   │   │                              │  │
│  │  1. PyMuPDF       │   │  1. Groq → Llama 3.3 70B    │  │
│  │  2. Tesseract OCR │──▶│  2. OR  → DeepSeek V3 free  │  │
│  │  3. PyPDF2        │   │  3. OR  → Gemma 4 26B free  │  │
│  │  (cascade, auto)  │   │  4. OR  → Llama 3.3 70B free│  │
│  └───────────────────┘   └──────────────────────────────┘  │
│                                                           │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Rate Limiting                                        │  │
│  │  100 calls/day · persisted to /data/sb_daily.json   │  │
│  │  Threading lock · counter increments on success only │  │
│  └──────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────┘
                      │
         Groq API + OpenRouter API
    (Llama 3.3 70B · DeepSeek V3 · Gemma 4 · free tier)
```

### Key Architectural Decisions

**Why Groq as the primary provider?**
Groq's LPU (Language Processing Unit) inference returns structured JSON in 2–4 seconds on free tier. GPU-based providers return the same output in 8–15 seconds. For a study tool where users are waiting, this difference is felt on every single interaction.

**Why a 4-model fallback chain?**
Free-tier models have per-minute rate limits. A single provider with no fallback means users hit error walls during burst usage. The chain retries automatically on any rate limit, quota, or provider error — the user sees a slight delay, not a failure. The counter only increments on a successful response, so exhausted calls don't burn quota.

**Why does one `/generate-extras` call feed three tabs?**
Flashcards, exam questions, and simple explanation are all generated in a single LLM call and cached. Splitting into three separate calls would cost 3× the quota and 3× the latency. One structured JSON response, three UI tabs populated simultaneously on first visit.

**Why lazy-load on tab click instead of eagerly generating everything?**
A user who uploads notes may only want the quiz. Generating all study aids upfront wastes 2 LLM calls on content they never view. Lazy loading generates data only when the user navigates to that tab — and caches it so the second visit is instant.

**Why remove per-session tracking entirely?**
The original design tracked every browser session via UUID, IP, and localStorage to prevent abuse. With Groq as primary (high RPM) and 3 fallbacks, one user can consume at most ~3 calls per upload. At 100 calls/day, the shared pool handles 33+ full sessions. The complexity of session management wasn't justified by the actual risk.

**Why vanilla JS with no framework?**
This is a portfolio piece that demonstrates state management, DOM manipulation, async flows, and lazy loading without abstractions. The result also has zero build time, zero dependencies, and sub-100ms page load.

---

## 🛠️ Tech Stack

| Layer | Choice | Why |
|---|---|---|
| **Primary LLM** | Groq — Llama 3.3 70B Versatile | Fastest free inference · 2–4s responses |
| **Fallback LLMs** | OpenRouter — DeepSeek V3 · Gemma 4 26B · Llama 3.3 70B | Free tier · auto-retry on rate limit |
| **LLM SDK** | `openai` (OpenRouter + Groq compatible) | Single SDK for all providers |
| **Backend** | FastAPI + Python 3.11 | Async endpoints · Pydantic native |
| **PDF — text** | PyMuPDF (fitz) | Fastest · most accurate on digital PDFs |
| **PDF — scanned** | pytesseract + pdf2image + poppler | OCR at 200 DPI for image-based PDFs |
| **PDF — fallback** | PyPDF2 | Legacy support |
| **Frontend** | Vanilla HTML / CSS / JS | No build step · zero dependencies |
| **Design** | Warm Light system | Cream bg · amber accent · readable contrast |
| **Backend host** | HuggingFace Spaces (Docker) | Free · persistent /data · full Dockerfile control |
| **Frontend host** | Vercel | Free CDN · GitHub auto-deploy |
| **CI/CD** | GitHub Actions | Push to `main` → auto-deploy to HF Spaces |

---

## 📁 Project Structure

```
studybuddy-ai/
├── app/
│   ├── main.py          # FastAPI app · LLM fallback chain · rate limiting · PDF extraction
│   └── prompts.py       # System prompts for all 4 study aid types
├── frontend/
│   ├── index.html       # Single-page app shell · tab structure · modals
│   ├── style.css        # Warm light theme · tab nav · responsive · animations
│   └── script.js        # State management · lazy loading · API calls · quiz engine
├── .github/
│   └── workflows/
│       └── deploy.yml   # GitHub Actions → HuggingFace Spaces CI/CD
├── Dockerfile           # python:3.11-slim · Tesseract · Poppler · port 7860
├── requirements.txt
└── README.md
```

---

## 🔌 API Endpoints

| Method | Endpoint | Description | Counts toward daily limit |
|---|---|---|---|
| `GET` | `/health` | Status · active model · fallback chain · daily remaining | No |
| `POST` | `/extract-pdf` | PDF text extraction (3-strategy cascade) | No |
| `POST` | `/process` | Analyse material → topic · difficulty · concepts · terms | Yes |
| `POST` | `/generate-quiz` | 10 MCQs with explanations + memory tips | Yes |
| `POST` | `/generate-extras` | Flashcards + exam questions + simple explanation | Yes |
| `POST` | `/followup` | Answer a follow-up question in plain language | Yes |

PDF extraction never counts toward the daily limit — only successful LLM responses do.

---

## ⚙️ CI/CD Pipeline

```
git push origin main
    │
    ├── GitHub Actions
    │       ├── Clone existing HF Space (preserves frontend files on HF)
    │       ├── Inject: app/ · requirements.txt · Dockerfile
    │       ├── Generate HF config YAML dynamically on runner
    │       └── Push to HF Space git → Docker rebuild → Space restart
    │
    └── Vercel detects push → rebuilds frontend → CDN propagation
```

**One-time setup:**
1. Get an HF token with Write access at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
2. Add as GitHub secret: `Repo → Settings → Secrets → Actions → HF_TOKEN`
3. Add `GROQ_API_KEY` and `OPENROUTER_API_KEY` to HF Space Secrets
4. Connect GitHub repo to Vercel for automatic frontend deploys

> API keys live exclusively in HF Space Secrets and are never committed to the repository.

---

## 🧪 Running Locally

**Prerequisites:** Python 3.11+, Tesseract OCR (`brew install tesseract` / `apt install tesseract-ocr`), Poppler

```bash
# Clone
git clone https://github.com/Gagandeep61/studybuddy-ai.git
cd studybuddy-ai

# Install Python dependencies
pip install -r requirements.txt

# Set environment variables
echo "GROQ_API_KEY=your_key_here" > .env
echo "OPENROUTER_API_KEY=your_key_here" >> .env

# Start backend
uvicorn app.main:app --reload --port 8000

# Frontend — open frontend/index.html with VS Code Live Server
# or: cd frontend && python -m http.server 3000
```

> Update `API_URL` in `script.js` to `http://localhost:8000` for local testing. The UI is fully visible without a backend connection — only AI features require it.

---

## 🧠 Key Learnings

**1. Multi-provider fallback is worth the setup cost.**
A single free-tier LLM provider will rate-limit during burst usage. Building the 4-model chain upfront meant the app never showed an error wall to users — it just silently retried. The OpenAI SDK's unified interface made swapping providers a one-string change.

**2. Increment the counter only on success.**
The original design incremented the daily counter before the LLM call. If the call failed, the count was wasted. Moving the increment inside the success path meant failed retries don't burn quota — only actual completions count.

**3. One API call feeding multiple features is both faster and cheaper.**
Splitting flashcards, exam questions, and simple explanation into three separate LLM calls would have tripled the quota cost and tripled the wait time. A single structured JSON response with three sections costs the same as one call and feels instantaneous across all three tabs.

**4. Lazy loading is the right default for AI-heavy UIs.**
Generating all study aids on upload would force users to wait 15+ seconds before seeing anything. Tab-based lazy loading shows results in 5 seconds (just the analysis) and fetches the rest on demand. Users who only want the quiz never pay the cost of generating flashcards.

**5. Free-tier constraints produce better architecture.**
The rate limits forced batching, lazy loading, and caching decisions that made the app faster and more efficient on paid tiers too — not just free ones.

**6. Session tracking is over-engineering for low-traffic demos.**
The first version had UUID tracking, IP abuse detection, 3-hour windows, and halved budgets for suspicious sessions. With higher daily limits from Groq, the entire system was replaced with three lines of daily counter code. Simpler, more reliable, easier to debug.

---

## 🐛 Notable Bugs Fixed

| Bug | Impact | Fix |
|---|---|---|
| Dockerfile `EXPOSE 7860` but uvicorn on `--port 8000` | App unreachable on HuggingFace — all requests dropped | Changed uvicorn port to `7860` |
| `max_tokens: 4096` on `/generate-extras` | Long study texts truncated JSON mid-response → parse error | Raised to `8192` + added partial JSON salvage fallback |
| Backend still required `X-Session-ID` after session tracking removal | Every API call returned `400 Missing X-Session-ID header` | Removed header requirement from `check_limits()` |
| `actions/checkout@v6` in deploy.yml — version doesn't exist | CI/CD failed on every push, backend never deployed | Changed to `@v5` + `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true` |
| Tabs in header row overflowed on mobile | Horizontal scrollbar appeared · "Explain Simply" tab invisible | Moved tabs to dedicated full-width sub-nav strip below header |
| `divider-v` (vertical "or") rendered as full-width horizontal bar on mobile | Upload layout broken on narrow screens | Hidden on mobile · replaced with `.mobile-or` text element |
| Daily counter incremented before LLM call | Failed retries consumed quota permanently | Moved `_increment_daily()` inside `call_llm()` success path |
| Race condition: concurrent requests could corrupt `sb_daily.json` | Counter could go negative or miss increments under load | Wrapped all read-write operations in `threading.Lock()` |

---

## 🗺️ Future Scope

| Feature | Approach |
|---|---|
| **Export study set as PDF** | reportlab · generate a formatted quiz + flashcard PDF for offline use |
| **Spaced repetition** | SM-2 algorithm on flashcard known/review signals · localStorage persistence |
| **Multi-language support** | Hindi · Punjabi output via language toggle — same prompt, language instruction appended |
| **Image and diagram support** | Vision model extraction for figure-heavy PDFs (textbooks, slides) |
| **Progress tracking** | IndexedDB · per-topic score history · weak topic identification over time |
| **Audio mode** | Web Speech API · read questions and flashcards aloud for commute studying |
| **Collaborative study sets** | Shared session links · multiple users on same study set simultaneously |

---

## 👨‍💻 Author

**Gagandeep Singh**

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-0077B5?style=flat&logo=linkedin)](https://www.linkedin.com/in/gagandeep-singh-517155319)
[![GitHub](https://img.shields.io/badge/GitHub-Follow-181717?style=flat&logo=github)](https://github.com/Gagandeep61)

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">
<sub>Built with Groq · OpenRouter · FastAPI · HuggingFace Spaces · Vercel</sub>
<br>
<sub>Active recall over passive re-reading — always.</sub>
</div>
