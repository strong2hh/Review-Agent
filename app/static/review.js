let sessionId = null;
let totalQuestions = 0;
let currentIndex = 1;
let currentQuestionId = null;
let sessionMode = "daily";

const progressEl = document.getElementById("progress");
const titleEl = document.getElementById("title");
const questionEl = document.getElementById("question");
const answerEl = document.getElementById("answer");
const resultEl = document.getElementById("result");
const submitBtn = document.getElementById("submit-btn");
const challengeActionsEl = document.getElementById("challenge-actions");
const challengeBtn = document.getElementById("challenge-btn");
const exitChallengeBtn = document.getElementById("exit-challenge-btn");

function toErrorMessage(err) {
  if (err instanceof Error && err.message) {
    return err.message;
  }
  return "请求失败，请稍后重试";
}

async function parseJsonOrThrow(resp) {
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const detail = typeof data.detail === "string" ? data.detail : "请求失败，请稍后重试";
    throw new Error(detail);
  }
  return data;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderMissingParts(parts) {
  if (!Array.isArray(parts) || parts.length === 0) {
    return "<p class=\"result-empty\">未发现明显遗漏要点。</p>";
  }
  return `<ul class="missing-list">${parts.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>`;
}

function setChallengeActions(visible, showExit = false) {
  challengeActionsEl.classList.toggle("visible", visible);
  challengeBtn.style.display = visible ? "inline-block" : "none";
  exitChallengeBtn.style.display = visible && showExit ? "inline-block" : "none";
}

function setAnswerVisible(visible) {
  answerEl.style.display = visible ? "block" : "none";
  submitBtn.style.display = visible ? "inline-block" : "none";
}

function updateProgress() {
  if (!totalQuestions) {
    progressEl.textContent = "当前没有待复习知识点，可以挑战一题。";
    return;
  }
  progressEl.textContent = `第 ${currentIndex} / ${totalQuestions} 题`;
}

function showDailyComplete() {
  sessionMode = "daily";
  titleEl.textContent = "今日复习已完成";
  questionEl.textContent = "";
  progressEl.textContent = totalQuestions ? `已完成 ${totalQuestions} / ${totalQuestions}` : "当前没有待复习知识点。";
  setAnswerVisible(false);
  setChallengeActions(true, false);
}

function ensureResultArea() {
  resultEl.style.display = "block";
}

function appendPendingGrading(jobId, title) {
  ensureResultArea();
  const card = document.createElement("div");
  card.className = "grading-card pending";
  card.id = `grading-job-${jobId}`;
  card.innerHTML = `
    <div><strong>${escapeHtml(title || "上一题")}</strong></div>
    <p class="result-empty">正在评分，请稍等...</p>
  `;
  resultEl.prepend(card);
  pollGradingJob(jobId, 0);
}

function renderCompletedGrading(card, data) {
  card.className = "grading-card completed";
  card.innerHTML = `
    <div><strong>${escapeHtml(data.title || "上一题")}</strong></div>
    <div><strong>得分：</strong>${data.score_0_100} / 100（${data.star_0_5} 星）</div>
    <div class="result-group">
      <strong>纠错建议（未回答部分）：</strong>
      ${renderMissingParts(data.missing_parts)}
    </div>
    <div class="result-group">
      <strong>正确答案：</strong>
      <div class="answer-scroll">${escapeHtml(data.correct_answer || "-")}</div>
    </div>
  `;
}

function renderFailedGrading(card, data) {
  card.className = "grading-card failed";
  card.innerHTML = `
    <div><strong>${escapeHtml(data.title || "上一题")}</strong></div>
    <p class="result-empty">评分失败：${escapeHtml(data.error || "请稍后重试")}</p>
  `;
}

async function pollGradingJob(jobId, attempt) {
  const card = document.getElementById(`grading-job-${jobId}`);
  if (!card) return;

  try {
    const resp = await fetch(`/api/review/grading-jobs/${jobId}`);
    const data = await parseJsonOrThrow(resp);
    if (data.status === "completed") {
      renderCompletedGrading(card, data);
      return;
    }
    if (data.status === "failed") {
      renderFailedGrading(card, data);
      return;
    }
  } catch (err) {
    if (attempt >= 60) {
      card.className = "grading-card failed";
      card.innerHTML = `<p class="result-empty">评分结果获取失败：${escapeHtml(toErrorMessage(err))}</p>`;
      return;
    }
  }

  if (attempt >= 120) {
    card.className = "grading-card failed";
    card.innerHTML = `<p class="result-empty">评分仍未完成，请稍后刷新页面查看。</p>`;
    return;
  }
  window.setTimeout(() => pollGradingJob(jobId, attempt + 1), 1200);
}

async function startSession() {
  sessionMode = "daily";
  setChallengeActions(false);
  let data;
  try {
    const resp = await fetch("/api/review/session/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    data = await parseJsonOrThrow(resp);
  } catch (err) {
    progressEl.textContent = `加载失败：${toErrorMessage(err)}`;
    setAnswerVisible(false);
    return;
  }

  sessionId = data.session_id;
  totalQuestions = data.total_questions;
  currentIndex = data.current_index || 1;
  currentQuestionId = data.question_id;
  if (!currentQuestionId) {
    showDailyComplete();
    return;
  }

  titleEl.textContent = data.title || "知识点";
  questionEl.textContent = "";
  answerEl.value = "";
  submitBtn.textContent = "提交并进入下一题";
  setAnswerVisible(true);
  updateProgress();
}

async function startChallenge() {
  sessionMode = "challenge";
  let data;
  try {
    const resp = await fetch("/api/review/challenge/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    data = await parseJsonOrThrow(resp);
  } catch (err) {
    progressEl.textContent = `挑战加载失败：${toErrorMessage(err)}`;
    setAnswerVisible(false);
    setChallengeActions(true, true);
    return;
  }

  sessionId = data.session_id;
  totalQuestions = data.total_questions;
  currentIndex = 1;
  currentQuestionId = data.question_id;
  if (!currentQuestionId) {
    titleEl.textContent = "暂无可挑战知识点";
    questionEl.textContent = "";
    progressEl.textContent = "没有可挑战的知识点，稍后再来。";
    setAnswerVisible(false);
    setChallengeActions(true, true);
    return;
  }

  titleEl.textContent = data.title || "挑战题";
  questionEl.textContent = "";
  progressEl.textContent = "挑战模式：自由作答，随时可以退出。";
  answerEl.value = "";
  submitBtn.textContent = "提交挑战答案";
  setAnswerVisible(true);
  setChallengeActions(true, true);
}

async function submitAnswer() {
  const answer = answerEl.value.trim();
  if (!answer) {
    alert("请先输入答案");
    return;
  }

  const submittedTitle = titleEl.textContent || "上一题";
  const wasChallenge = sessionMode === "challenge";
  submitBtn.disabled = true;
  submitBtn.textContent = "提交中...";
  let data;
  try {
    const resp = await fetch(`/api/review/session/${sessionId}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer }),
    });
    data = await parseJsonOrThrow(resp);
  } catch (err) {
    ensureResultArea();
    const card = document.createElement("div");
    card.className = "grading-card failed";
    card.innerHTML = `<strong>提交失败：</strong>${escapeHtml(toErrorMessage(err))}`;
    resultEl.prepend(card);
    submitBtn.disabled = false;
    submitBtn.textContent = wasChallenge ? "提交挑战答案" : "提交并进入下一题";
    return;
  }

  appendPendingGrading(data.grading_job_id, submittedTitle);

  if (wasChallenge) {
    titleEl.textContent = "挑战题已提交";
    questionEl.textContent = "";
    progressEl.textContent = "正在评分。你可以继续挑战下一题，或退出挑战。";
    setAnswerVisible(false);
    setChallengeActions(true, true);
    return;
  }

  if (data.completed) {
    showDailyComplete();
    return;
  }

  currentIndex += 1;
  currentQuestionId = data.next_question_id;
  titleEl.textContent = data.next_title || "知识点";
  questionEl.textContent = "";
  answerEl.value = "";
  submitBtn.disabled = false;
  submitBtn.textContent = "提交并进入下一题";
  setChallengeActions(false);
  updateProgress();
}

submitBtn.addEventListener("click", submitAnswer);
challengeBtn.addEventListener("click", startChallenge);
exitChallengeBtn.addEventListener("click", showDailyComplete);
startSession();
