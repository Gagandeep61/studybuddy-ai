/* StudyBuddy AI — script.js */

const API_URL = "https://gagan61-studybuddy-ai.hf.space";

// ── State ─────────────────────────────────────────────────────────────────────
const state = {
  rawText: "", processedData: null,
  quizQuestions: [], quizIndex: 0, quizAnswers: [],
  extras: null,
  fcIndex: 0, fcKnown: new Set(), fcDeck: [],
  followupCount: 0,
  callsUsed: 0,       // local session count, resets on page reload
  _pendingFile: null,
};

const $ = id => document.getElementById(id);

// ── Tabs ──────────────────────────────────────────────────────────────────────
document.querySelectorAll(".tab").forEach(btn => {
  btn.addEventListener("click", () => {
    if (btn.disabled) return;
    document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
    document.querySelectorAll(".tab").forEach(b => {
      b.classList.remove("active", "has-badge");
      b.removeAttribute("aria-selected");
    });
    $(`tab-${btn.dataset.tab}`).classList.add("active");
    btn.classList.add("active");
    btn.setAttribute("aria-selected", "true");
  });
});

function switchTab(name) { document.querySelector(`.tab[data-tab="${name}"]`)?.click(); }

function unlockTab(name) {
  const tab = document.querySelector(`.tab[data-tab="${name}"]`);
  if (!tab) return;
  tab.disabled = false;
  tab.removeAttribute("aria-disabled");
  const lock = tab.querySelector(".tab-lock");
  if (lock) lock.remove();
  tab.classList.add("has-badge", "new-unlock");
  setTimeout(() => tab.classList.remove("new-unlock"), 1650);
}

// ── Toast ─────────────────────────────────────────────────────────────────────
let toastTimer;
function toast(msg, type = "") {
  clearTimeout(toastTimer);
  const t = $("toast");
  t.textContent = msg; t.className = "toast " + type;
  t.classList.remove("hidden");
  toastTimer = setTimeout(() => t.classList.add("hidden"), 3500);
}

// ── Call counter (local, informational only) ──────────────────────────────────
function updateCounter() {
  state.callsUsed++;
  const visualPct = Math.min(100, (state.callsUsed / 15) * 100);
  $("callsFill").style.width = visualPct + "%";
  $("callsLabel").textContent = `${state.callsUsed} used`;
}

// ── Daily limit modal ─────────────────────────────────────────────────────────
function showLimitModal() {
  $("limitModal").classList.remove("hidden");
}

// ── API fetch ─────────────────────────────────────────────────────────────────
async function api(endpoint, body, isForm = false) {
  const opts = { method: "POST", headers: {} };
  if (isForm) { opts.body = body; }
  else { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }

  const res = await fetch(`${API_URL}${endpoint}`, opts);

  if (res.status === 503) { showLimitModal(); throw new Error("Daily limit reached."); }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "API error");
  }

  updateCounter();
  return res.json();
}

// ═══════════════════════════════════════════════════════════════════════════════
// TAB 1 — UPLOAD
// ═══════════════════════════════════════════════════════════════════════════════

const dropZone = $("dropZone");
dropZone.addEventListener("dragover",  e => { e.preventDefault(); dropZone.classList.add("drag-over"); });
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
dropZone.addEventListener("drop", e => { e.preventDefault(); dropZone.classList.remove("drag-over"); if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]); });
dropZone.addEventListener("click", () => $("fileInput").click());
$("fileInput").addEventListener("change", () => { if ($("fileInput").files[0]) setFile($("fileInput").files[0]); });

function setFile(f) { state._pendingFile = f; $("dropFilename").textContent = f.name; }

$("processBtn").addEventListener("click", async () => {
  const btn = $("processBtn");
  const pasteText = $("pasteText").value.trim();
  let text = "";

  if (pasteText) {
    text = pasteText;
  } else if (state._pendingFile) {
    if (state._pendingFile.type === "application/pdf") {
      try {
        const fd = new FormData(); fd.append("file", state._pendingFile);
        const d = await api("/extract-pdf", fd, true); text = d.text;
      } catch (e) { toast("PDF error: " + e.message, "error"); return; }
    } else { text = await state._pendingFile.text(); }
  } else { toast("Upload a file or paste text first.", "error"); return; }

  if (text.length < 100) { toast("Text too short.", "error"); return; }
  state.rawText = text;
  btn.disabled = true; btn.textContent = "Analysing…";

  try {
    const data = await api("/process", { text });
    state.processedData = data;
    renderSummary(data);
    unlockTab("quiz");
    toast("Done ✓ — Quiz tab is now available!", "success");
  } catch (e) { toast("Error: " + e.message, "error"); }
  finally { btn.disabled = false; btn.textContent = "Analyse →"; }
});

function renderSummary(d) {
  $("summarySubject").textContent = d.subject_area;
  $("summaryTopic").textContent   = d.topic;
  const dc = $("difficultyChip");
  dc.textContent = d.difficulty; dc.className = `chip ${d.difficulty?.toLowerCase()}`;
  $("wordChip").textContent = `${d.word_count?.toLocaleString()} words`;
  $("timeChip").textContent = `~${d.study_time_min}min`;

  const ul = $("conceptList"); ul.innerHTML = "";
  (d.summary_points||[]).forEach(p => { const li = document.createElement("li"); li.textContent = p; ul.appendChild(li); });

  const tc = $("termChips"); tc.innerHTML = "";
  (d.key_terms||[]).forEach(t => { const s = document.createElement("span"); s.className = "tag"; s.textContent = t; tc.appendChild(s); });

  $("summaryCard").classList.remove("hidden");
  $("summaryCard").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

$("loadExtrasBtn").addEventListener("click", async () => {
  if (state.extras) { toast("Already generated!", "success"); ["flashcards","exam","simple"].forEach(unlockTab); return; }
  const btn = $("loadExtrasBtn"); btn.disabled = true; btn.textContent = "Generating…";
  try {
    const data = await api("/generate-extras", { text: state.rawText });
    state.extras = data;
    ["flashcards","exam","simple"].forEach(unlockTab);
    renderFlashcards(data.flashcards);
    renderExamQuestions(data.exam_questions);
    renderSimple(data.simple_explanation);
    toast("Study aids ready ✓ — 3 new tabs unlocked!", "success");
  } catch (e) { toast("Error: " + e.message, "error"); }
  finally { btn.disabled = false; btn.textContent = "Generate study aids"; }
});

$("goToQuizBtn").addEventListener("click", () => switchTab("quiz"));

// ═══════════════════════════════════════════════════════════════════════════════
// TAB 2 — QUIZ
// ═══════════════════════════════════════════════════════════════════════════════

$("generateQuizBtn").addEventListener("click", async () => {
  const btn = $("generateQuizBtn"); btn.disabled = true; btn.textContent = "Generating…";
  try {
    const data = await api("/generate-quiz", { text: state.rawText });
    state.quizQuestions = data.questions; state.quizIndex = 0; state.quizAnswers = [];
    $("quizIdle").classList.add("hidden");
    $("quizWrap").classList.remove("hidden");
    $("quizTotal").textContent = data.questions.length;
    renderQuestion();
  } catch (e) { toast("Error: " + e.message, "error"); btn.disabled = false; btn.textContent = "Generate Quiz →"; }
});

function renderQuestion() {
  const q = state.quizQuestions[state.quizIndex]; if (!q) return;
  $("quizCurrent").textContent  = state.quizIndex + 1;
  $("quizTag").textContent      = q.topic_tag || "";
  $("quizFill").style.width     = `${(state.quizIndex / state.quizQuestions.length) * 100}%`;
  $("questionText").textContent = q.question;

  const grid = $("optionsGrid"); grid.innerHTML = "";
  ["A","B","C","D"].forEach((letter, i) => {
    const btn = document.createElement("button"); btn.className = "option-btn";
    btn.innerHTML = `<span class="opt-key">${letter}</span><span>${q.options[i]}</span>`;
    btn.addEventListener("click", () => handleAnswer(i, q));
    grid.appendChild(btn);
  });

  $("feedbackBox").classList.add("hidden");
  $("feedbackBox").className = "feedback hidden";
  $("nextBtn").classList.add("hidden");
  const card = $("questionCard"); card.style.animation = "none"; requestAnimationFrame(() => { card.style.animation = ""; });
}

function handleAnswer(idx, q) {
  document.querySelectorAll(".option-btn").forEach(b => b.disabled = true);
  const correct = idx === q.correct_index;
  state.quizAnswers.push({ is_correct: correct, topic_tag: q.topic_tag });
  document.querySelectorAll(".option-btn")[q.correct_index].classList.add("correct");
  if (!correct) document.querySelectorAll(".option-btn")[idx].classList.add("incorrect");

  const exp = correct ? q.correct_explanation : (q.wrong_explanations?.[String(idx)] || q.correct_explanation);
  const fb  = $("feedbackBox");
  fb.className = `feedback ${correct ? "correct-fb" : "incorrect-fb"}`;
  fb.innerHTML = `<span>${exp}</span>${q.memory_tip ? `<p class="fb-tip">💡 ${q.memory_tip}</p>` : ""}`;
  fb.classList.remove("hidden");
  $("nextBtn").classList.remove("hidden");
}

$("nextBtn").addEventListener("click", () => {
  state.quizIndex++;
  if (state.quizIndex >= state.quizQuestions.length) renderScore();
  else renderQuestion();
});

function renderScore() {
  $("quizWrap").classList.add("hidden");
  const correct = state.quizAnswers.filter(a => a.is_correct).length;
  const total   = state.quizAnswers.length;
  const pct     = Math.round((correct / total) * 100);
  const weak    = [...new Set(state.quizAnswers.filter(a => !a.is_correct).map(a => a.topic_tag).filter(Boolean))];
  const sc      = $("scoreCard");
  sc.innerHTML  = `
    <span class="score-number">${correct}/${total}</span>
    <p style="color:var(--text-2)">${pct}% — ${pct>=80?"Excellent!":pct>=60?"Good effort!":"Keep studying!"}</p>
    ${weak.length ? `<div class="score-weak"><p class="weak-label">Review these topics</p>${weak.map(t=>`<span class="weak-tag">${t}</span>`).join("")}</div>` : ""}
    <div class="score-actions">
      <button class="btn-secondary" onclick="retakeQuiz()">Retake</button>
      <button class="btn-primary" onclick="switchTab('flashcards')">Flashcards →</button>
    </div>`;
  sc.classList.remove("hidden");
  try {
    const h = JSON.parse(localStorage.getItem("sb_scores")||"[]");
    h.unshift({correct,total,topic:state.processedData?.topic,date:new Date().toLocaleDateString()});
    localStorage.setItem("sb_scores", JSON.stringify(h.slice(0,3)));
  } catch {}
}

function retakeQuiz() {
  $("scoreCard").classList.add("hidden");
  state.quizIndex = 0; state.quizAnswers = [];
  $("quizWrap").classList.remove("hidden");
  renderQuestion();
}

// ═══════════════════════════════════════════════════════════════════════════════
// TAB 3 — FLASHCARDS
// ═══════════════════════════════════════════════════════════════════════════════

function renderFlashcards(cards) {
  if (!cards?.length) return;
  state.fcDeck = cards.map((_,i)=>i); state.fcIndex = 0; state.fcKnown = new Set();
  $("fcTotal").textContent = cards.length;
  $("flashcardsLoading").classList.add("hidden");
  $("flashcardWrap").classList.remove("hidden");
  showCard();
}
function showCard() {
  const c = state.extras.flashcards[state.fcDeck[state.fcIndex]]; if (!c) return;
  $("flashcard").classList.remove("flipped");
  setTimeout(() => { $("fcTerm").textContent = c.term; $("fcDef").textContent = c.definition; $("fcKnown").textContent = state.fcKnown.size; }, 150);
}
$("flashcard").addEventListener("click",  () => $("flashcard").classList.toggle("flipped"));
$("fcPrev").addEventListener("click",     () => { if (state.fcIndex > 0) { state.fcIndex--; showCard(); } });
$("fcNext").addEventListener("click",     () => { if (state.fcIndex < state.fcDeck.length-1) { state.fcIndex++; showCard(); } });
$("fcKnownBtn").addEventListener("click", () => { state.fcKnown.add(state.fcDeck[state.fcIndex]); $("fcKnown").textContent = state.fcKnown.size; if (state.fcIndex < state.fcDeck.length-1) { state.fcIndex++; showCard(); } else toast("All cards done! 🎉","success"); });
$("fcReview").addEventListener("click",   () => { state.fcKnown.delete(state.fcDeck[state.fcIndex]); if (state.fcIndex < state.fcDeck.length-1) { state.fcIndex++; showCard(); } });
$("fcShuffle").addEventListener("click",  () => { state.fcDeck = state.fcDeck.sort(()=>Math.random()-.5); state.fcIndex=0; showCard(); toast("Shuffled!"); });

// ═══════════════════════════════════════════════════════════════════════════════
// TAB 4 — EXAM PREP
// ═══════════════════════════════════════════════════════════════════════════════

function renderExamQuestions(qs) {
  if (!qs?.length) return;
  $("examLoading").classList.add("hidden");
  const list = $("examList"); list.classList.remove("hidden"); list.innerHTML = "";
  qs.forEach((q,i) => {
    const el = document.createElement("div"); el.className = "exam-item";
    el.style.animationDelay = `${i*0.06}s`;
    el.innerHTML = `
      <button class="exam-q-btn">
        <div class="exam-q-left"><span class="exam-num">0${i+1}</span><span class="exam-q-text">${q.question}</span></div>
        <span class="exam-chevron">↓</span>
      </button>
      <div class="exam-details">
        <p class="exam-hint">Hint: ${q.hint}</p>
        <ul class="exam-points">${(q.key_points||[]).map(p=>`<li>${p}</li>`).join("")}</ul>
      </div>`;
    el.querySelector(".exam-q-btn").addEventListener("click", () => el.classList.toggle("open"));
    list.appendChild(el);
  });
}

// ═══════════════════════════════════════════════════════════════════════════════
// TAB 5 — EXPLAIN SIMPLY
// ═══════════════════════════════════════════════════════════════════════════════

function renderSimple(text) {
  if (!text) return;
  $("simpleLoading").classList.add("hidden");
  $("simpleWrap").classList.remove("hidden");
  const w = $("simpleText"); w.innerHTML = "";
  text.split(/\n+/).filter(p=>p.trim()).forEach(p => { const el = document.createElement("p"); el.textContent = p; w.appendChild(el); });
}

$("followupBtn").addEventListener("click", sendFollowup);
$("followupInput").addEventListener("keydown", e => { if (e.key === "Enter") sendFollowup(); });

async function sendFollowup() {
  const q = $("followupInput").value.trim(); if (!q) return;
  if (state.followupCount >= 3) { toast("Follow-up limit reached (3 max).", "error"); return; }
  const btn = $("followupBtn"); btn.disabled = true; btn.textContent = "…";
  const resp = $("followupResponse");
  resp.classList.remove("hidden"); resp.textContent = "Thinking…";
  try {
    const d = await api("/followup", { context: $("simpleText").textContent, topic: state.processedData?.topic||"", question: q, followup_count: state.followupCount });
    resp.textContent = d.answer;
    state.followupCount++;
    $("followupInput").value = "";
    const rem = 3 - state.followupCount;
    $("followupCounter").textContent = rem > 0 ? `(${rem} remaining)` : "(limit reached)";
    if (rem === 0) { $("followupInput").disabled = true; btn.textContent = "Limit reached"; return; }
  } catch (e) { resp.textContent = "Error: " + e.message; }
  btn.disabled = false; btn.textContent = "Ask";
}

// ── Init ──────────────────────────────────────────────────────────────────────
(async () => {
  try {
    const res = await fetch(`${API_URL}/health`);
    $("statusDot").className = res.ok ? "status-dot connected" : "status-dot error";
    if (!res.ok) toast("API offline — start the backend.", "error");
  } catch {
    $("statusDot").className = "status-dot error";
    toast("Backend not reachable.", "error");
  }
})();
